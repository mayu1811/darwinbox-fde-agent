"""Deterministic, reversible cleaning.

Rule of thumb applied throughout: a transformation is automatic only if it is
(a) deterministic, (b) reversible from the audit trail, and (c) cannot change
the meaning of the value. Trimming whitespace qualifies. Guessing whether
'12/08/2025' is August or December does not - which is why the day-first
decision is made once per COLUMN from evidence, not per value.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import get_target_schema
from ..utils.dates import parse_date
from ..utils.text import (
    collapse_whitespace,
    is_blank,
    normalise_email,
    normalise_person_name,
    normalise_phone,
    sanitize_cell,
    slugify,
    title_case_label,
)


@dataclass
class Change:
    field: str
    before: str | None
    after: str | None
    rule: str
    reversible: bool = True

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "before": self.before,
            "after": self.after,
            "rule": self.rule,
            "reversible": self.reversible,
            "actor": "agent",
        }


@dataclass
class CleanIssue:
    field: str
    value: str
    message: str
    safe_to_drop: bool


def _enum_lookup() -> dict[str, dict[str, str]]:
    schema = get_target_schema()
    table: dict[str, dict[str, str]] = {}
    for field_name, mapping in schema.get("enum_normalisation", {}).items():
        table[field_name] = {}
        for canonical, variants in mapping.items():
            table[field_name][slugify(canonical)] = canonical
            for variant in variants:
                table[field_name][slugify(variant)] = canonical
    return table


def clean_record(
    mapped: dict[str, str], column_hints: dict[str, dict] | None = None
) -> tuple[dict, list[Change], list[CleanIssue]]:
    """Normalise one target-shaped record.

    `column_hints` carries per-target-field profile information (notably
    `day_first`) derived once from the whole column.
    """
    schema = get_target_schema()["fields"]
    enums = _enum_lookup()
    hints = column_hints or {}

    cleaned: dict[str, str | None] = {}
    changes: list[Change] = []
    issues: list[CleanIssue] = []

    for target_field, spec in schema.items():
        raw = mapped.get(target_field)
        if is_blank(raw):
            cleaned[target_field] = None
            continue

        original = str(raw)
        value: str | None = sanitize_cell(original)
        ftype = spec.get("type", "string")

        # 1. whitespace - always safe
        trimmed = collapse_whitespace(value)
        if trimmed != value:
            changes.append(Change(target_field, original, trimmed, "trim_whitespace"))
        value = trimmed

        # 2. type-specific normalisation
        if ftype == "email":
            normalised = normalise_email(value)
            if normalised != value:
                changes.append(Change(target_field, value, normalised, "lowercase_email"))
            value = normalised

        elif ftype == "date":
            day_first = hints.get(target_field, {}).get("day_first", True)
            result = parse_date(value, day_first=day_first)
            if result.ok:
                if result.iso != value:
                    changes.append(
                        Change(
                            target_field,
                            value,
                            result.iso,
                            f"parse_date({result.format_used}) -> ISO-8601",
                        )
                    )
                value = result.iso
            else:
                issues.append(
                    CleanIssue(
                        field=target_field,
                        value=value,
                        message=result.error or "unparseable date",
                        # Optional dates can be dropped safely; mandatory ones cannot.
                        safe_to_drop=not spec.get("required", False),
                    )
                )
                value = None

        elif ftype == "phone":
            normalised = normalise_phone(value)
            if normalised is None:
                issues.append(
                    CleanIssue(
                        field=target_field,
                        value=value,
                        message="phone number does not match a known format",
                        safe_to_drop=not spec.get("required", False),
                    )
                )
                value = None
            else:
                if normalised != value:
                    changes.append(
                        Change(target_field, value, normalised, "normalise_phone(E.164)")
                    )
                value = normalised

        elif ftype == "enum":
            key = slugify(value)
            canonical = enums.get(target_field, {}).get(key)
            if canonical is None:
                issues.append(
                    CleanIssue(
                        field=target_field,
                        value=value,
                        message=(
                            f"value '{value}' is not a recognised {target_field}; "
                            f"allowed: {spec.get('values')}"
                        ),
                        safe_to_drop=False,
                    )
                )
                value = None
            else:
                if canonical != value:
                    changes.append(
                        Change(target_field, value, canonical, "normalise_enum")
                    )
                value = canonical

        elif target_field == "full_name":
            normalised = normalise_person_name(value)
            if normalised != value:
                changes.append(Change(target_field, value, normalised, "normalise_name_casing"))
            value = normalised

        elif target_field in ("department", "designation"):
            normalised = title_case_label(value)
            if normalised != value:
                changes.append(Change(target_field, value, normalised, "normalise_label_casing"))
            value = normalised

        elif target_field == "employee_id":
            normalised = value.upper().replace(" ", "")
            if normalised != value:
                changes.append(Change(target_field, value, normalised, "normalise_identifier"))
            value = normalised

        cleaned[target_field] = value

    return cleaned, changes, issues
