"""Validation against the target schema, with bounded automatic repair.

The agent gets at most `max_auto_repair_attempts` goes at fixing a record.
After that it stops guessing and asks a human - an agent that keeps retrying a
repair it cannot do is just a slower way to corrupt data.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import get_target_schema, settings
from ..utils.dates import parse_date
from ..utils.text import is_blank, is_valid_email, normalise_email, slugify


@dataclass
class ValidationIssue:
    field: str
    code: str
    message: str
    value: str | None = None
    repairable: bool = False

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "code": self.code,
            "message": self.message,
            "value": self.value,
            "repairable": self.repairable,
        }


def validate_record(record: dict) -> list[ValidationIssue]:
    schema = get_target_schema()["fields"]
    issues: list[ValidationIssue] = []

    for name, spec in schema.items():
        value = record.get(name)

        if spec.get("required") and is_blank(value):
            issues.append(
                ValidationIssue(
                    field=name,
                    code="required_missing",
                    message=f"'{name}' is mandatory in the target schema but is empty",
                    value=None,
                    repairable=name == "email",  # may be recoverable from a duplicate row
                )
            )
            continue

        if is_blank(value):
            continue

        ftype = spec.get("type", "string")
        text = str(value)

        if ftype == "email" and not is_valid_email(text):
            issues.append(
                ValidationIssue(
                    field=name,
                    code="invalid_email",
                    message=f"'{text}' is not a valid email address",
                    value=text,
                    repairable=text != normalise_email(text),
                )
            )
        elif ftype == "date":
            if not parse_date(text, day_first=True).ok:
                issues.append(
                    ValidationIssue(
                        field=name,
                        code="invalid_date",
                        message=f"'{text}' is not a valid {spec.get('format', 'date')}",
                        value=text,
                        repairable=False,
                    )
                )
        elif ftype == "enum":
            allowed = [str(v) for v in spec.get("values", [])]
            if text not in allowed:
                issues.append(
                    ValidationIssue(
                        field=name,
                        code="invalid_enum",
                        message=f"'{text}' is not one of {allowed}",
                        value=text,
                        repairable=slugify(text) in {slugify(a) for a in allowed},
                    )
                )
        elif ftype == "phone" and not text.startswith("+"):
            issues.append(
                ValidationIssue(
                    field=name,
                    code="invalid_phone",
                    message=f"'{text}' is not in E.164 format",
                    value=text,
                    repairable=True,
                )
            )

    return issues


def attempt_repair(record: dict, issues: list[ValidationIssue]) -> tuple[dict, list[dict]]:
    """Try to fix issues that have a single deterministic answer.

    Returns (possibly updated record, list of repair descriptions).
    """
    from ..utils.text import normalise_phone

    schema = get_target_schema()["fields"]
    repaired = dict(record)
    applied: list[dict] = []

    for issue in issues:
        if not issue.repairable:
            continue
        before = repaired.get(issue.field)

        if issue.code == "invalid_email" and before:
            candidate = normalise_email(str(before))
            if is_valid_email(candidate):
                repaired[issue.field] = candidate
                applied.append(
                    {
                        "field": issue.field,
                        "before": before,
                        "after": candidate,
                        "rule": "repair_email_casing_whitespace",
                    }
                )
        elif issue.code == "invalid_enum" and before:
            allowed = [str(v) for v in schema[issue.field].get("values", [])]
            match = next((a for a in allowed if slugify(a) == slugify(str(before))), None)
            if match:
                repaired[issue.field] = match
                applied.append(
                    {
                        "field": issue.field,
                        "before": before,
                        "after": match,
                        "rule": "repair_enum_casing",
                    }
                )
        elif issue.code == "invalid_phone" and before:
            candidate = normalise_phone(str(before))
            if candidate:
                repaired[issue.field] = candidate
                applied.append(
                    {
                        "field": issue.field,
                        "before": before,
                        "after": candidate,
                        "rule": "repair_phone_format",
                    }
                )

    return repaired, applied


def check_unique_employee_ids(records: list[dict]) -> dict[str, list[int]]:
    """Return {employee_id: [indices]} for ids appearing more than once."""
    seen: dict[str, list[int]] = {}
    for idx, rec in enumerate(records):
        emp_id = rec.get("employee_id")
        if is_blank(emp_id):
            continue
        seen.setdefault(str(emp_id).strip().upper(), []).append(idx)
    return {k: v for k, v in seen.items() if len(v) > 1}


MAX_REPAIR_ATTEMPTS = settings.max_auto_repair_attempts
