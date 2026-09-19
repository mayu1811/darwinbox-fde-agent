"""Deterministic deduplication and field-level reconciliation.

Matching ladder (first hit wins):
  1. employee_id            - exact, the target primary key
  2. normalised email       - exact
  3. normalised name + phone - fuzzy fallback for rows missing both keys

Merging policy:
  * identical values                 -> merge silently
  * one side empty, other populated  -> fill (a gain of information, reversible)
  * conflicting NON-critical field   -> resolve by source precedence, audited
  * conflicting CRITICAL field       -> escalate; the agent will not pick an
    identity or an employment status on the client's behalf
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import get_target_schema
from ..utils.text import is_blank, normalise_email, slugify

#: Fields where a conflict is a business decision, not a data-quality nit.
CRITICAL_CONFLICT_FIELDS = {"employee_id", "full_name", "email", "status"}


@dataclass
class FieldConflict:
    field_name: str
    values: list[dict]  # [{value, source_file, row}]
    resolved_value: str | None = None
    resolution_rule: str | None = None
    confidence: float = 0.0
    needs_human: bool = False


@dataclass
class MergeResult:
    survivor_index: int
    merged_indices: list[int] = field(default_factory=list)
    match_rule: str = "employee_id"
    match_confidence: float = 1.0
    merged_values: dict = field(default_factory=dict)
    conflicts: list[FieldConflict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _identity_keys(record: dict) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    emp_id = record.get("employee_id")
    if not is_blank(emp_id):
        keys.append(("employee_id", str(emp_id).strip().upper()))
    email = record.get("email")
    if not is_blank(email):
        keys.append(("email", normalise_email(str(email))))
    name, phone = record.get("full_name"), record.get("mobile_phone")
    if not is_blank(name) and not is_blank(phone):
        digits = "".join(ch for ch in str(phone) if ch.isdigit())[-10:]
        keys.append(("name_phone", f"{slugify(str(name))}|{digits}"))
    return keys


MATCH_CONFIDENCE = {"employee_id": 1.0, "email": 0.97, "name_phone": 0.88}


def find_duplicate_groups(records: list[dict]) -> list[list[int]]:
    """Union-find over the identity ladder. Returns groups of >= 2 indices."""
    parent = list(range(len(records)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    seen: dict[tuple[str, str], int] = {}
    for idx, rec in enumerate(records):
        for key in _identity_keys(rec):
            if key in seen:
                union(seen[key], idx)
            else:
                seen[key] = idx

    groups: dict[int, list[int]] = {}
    for idx in range(len(records)):
        groups.setdefault(find(idx), []).append(idx)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def _match_rule(records: list[dict], indices: list[int]) -> tuple[str, float]:
    ids = {str(records[i].get("employee_id") or "").strip().upper() for i in indices}
    ids.discard("")
    if len(ids) == 1 and ids:
        return "employee_id", MATCH_CONFIDENCE["employee_id"]
    emails = {normalise_email(str(records[i].get("email") or "")) for i in indices}
    emails.discard("")
    if len(emails) == 1 and emails:
        return "normalised_email", MATCH_CONFIDENCE["email"]
    return "name_and_phone", MATCH_CONFIDENCE["name_phone"]


def reconcile_group(
    records: list[dict],
    indices: list[int],
    precedence: dict[int, int],
) -> MergeResult:
    """Merge a duplicate group. `precedence` maps index -> priority (higher wins)."""
    schema = get_target_schema()["fields"]
    ordered = sorted(indices, key=lambda i: (-precedence.get(i, 0), i))
    survivor = ordered[0]
    rule, confidence = _match_rule(records, indices)

    result = MergeResult(
        survivor_index=survivor,
        merged_indices=[i for i in indices if i != survivor],
        match_rule=rule,
        match_confidence=confidence,
    )

    for target_field in schema:
        observations: list[dict] = []
        for i in ordered:
            value = records[i].get(target_field)
            if is_blank(value):
                continue
            observations.append(
                {
                    "value": str(value),
                    "index": i,
                    "source_file": records[i].get("__source_file", "?"),
                    "row": records[i].get("__row", 0),
                }
            )

        if not observations:
            result.merged_values[target_field] = None
            continue

        distinct = {o["value"] for o in observations}
        if len(distinct) == 1:
            result.merged_values[target_field] = observations[0]["value"]
            if len(observations) < len(indices):
                result.notes.append(
                    f"{target_field}: filled from "
                    f"{observations[0]['source_file']} (missing in the other row)"
                )
            continue

        conflict = FieldConflict(
            field_name=target_field,
            values=[
                {"value": o["value"], "source_file": o["source_file"], "row": o["row"]}
                for o in observations
            ],
        )
        if target_field in CRITICAL_CONFLICT_FIELDS:
            conflict.needs_human = True
            conflict.confidence = 0.0
            conflict.resolution_rule = "escalate_critical_conflict"
            result.merged_values[target_field] = observations[0]["value"]
        else:
            winner = observations[0]  # highest precedence source
            conflict.resolved_value = winner["value"]
            conflict.resolution_rule = "source_precedence"
            conflict.confidence = 0.82
            result.merged_values[target_field] = winner["value"]
            result.notes.append(
                f"{target_field}: kept '{winner['value']}' from {winner['source_file']} "
                f"over {', '.join(repr(o['value']) for o in observations[1:])} "
                "(source precedence, non-critical field)"
            )
        result.conflicts.append(conflict)

    return result
