"""Profile a source file: for each column infer a semantic type + statistics.

The profile feeds two things:
  1. the mapping agent (value-level evidence, not just the column name), and
  2. the cleaning stage (e.g. is this column day-first or month-first?).
"""
from __future__ import annotations

from collections import Counter

from ..utils.dates import detect_day_first, looks_like_date_column
from ..utils.text import (
    is_blank,
    looks_like_email,
    looks_like_extension,
    looks_like_mobile,
    slugify,
)

SAMPLE_SIZE = 5


def _infer_type(values: list[str]) -> tuple[str, float]:
    non_empty = [v for v in values if not is_blank(v)]
    if not non_empty:
        return "unknown", 0.0

    email_ratio = looks_like_email(non_empty)
    if email_ratio >= 0.8:
        return "email", email_ratio

    date_ratio = looks_like_date_column(non_empty)
    if date_ratio >= 0.8:
        return "date", date_ratio

    digit_ratio = sum(
        1 for v in non_empty if sum(ch.isdigit() for ch in str(v)) >= 7
    ) / len(non_empty)
    if digit_ratio >= 0.8:
        return "phone", digit_ratio

    distinct = len({str(v).strip().lower() for v in non_empty})
    if distinct <= 6 and len(non_empty) >= 5:
        return "enum", 1.0 - (distinct / max(len(non_empty), 1))

    if all(str(v).strip().isdigit() for v in non_empty):
        return "integer", 1.0

    distinct_ratio = distinct / len(non_empty)
    if distinct_ratio > 0.9:
        return "identifier_or_text", distinct_ratio

    return "string", 0.6


def profile_column(name: str, values: list[str]) -> dict:
    non_empty = [v for v in values if not is_blank(v)]
    semantic_type, type_confidence = _infer_type(values)
    distinct = {str(v).strip() for v in non_empty}
    counter = Counter(str(v).strip().lower() for v in non_empty)

    profile = {
        "name": name,
        "key": slugify(name),
        "semantic_type": semantic_type,
        "type_confidence": round(type_confidence, 3),
        "count": len(values),
        "non_empty": len(non_empty),
        "null_ratio": round(1 - (len(non_empty) / len(values)), 3) if values else 1.0,
        "distinct": len(distinct),
        "unique_ratio": round(len(distinct) / len(non_empty), 3) if non_empty else 0.0,
        "samples": [str(v) for v in non_empty[:SAMPLE_SIZE]],
        "top_values": [{"value": v, "count": c} for v, c in counter.most_common(5)],
        "has_leading_trailing_space": any(str(v) != str(v).strip() for v in non_empty),
        "mixed_case": any(str(v).isupper() for v in non_empty)
        and any(str(v).islower() for v in non_empty),
        "signals": {
            "mobile_like": round(looks_like_mobile(non_empty), 3),
            "extension_like": round(looks_like_extension(non_empty), 3),
            "email_like": round(looks_like_email(non_empty), 3),
            "date_like": round(looks_like_date_column(non_empty), 3),
        },
    }
    if semantic_type == "date":
        profile["day_first"] = detect_day_first(non_empty)
    return profile


def infer_schema(columns: list[str], rows: list[dict]) -> dict:
    """Build {column_name: profile} for a whole file."""
    schema: dict[str, dict] = {}
    for col in columns:
        values = [r["raw"].get(col, "") for r in rows]
        schema[col] = profile_column(col, values)
    return schema


def summarise(schema: dict) -> dict:
    types = Counter(p["semantic_type"] for p in schema.values())
    return {
        "column_count": len(schema),
        "types": dict(types),
        "columns_with_whitespace": [
            n for n, p in schema.items() if p["has_leading_trailing_space"]
        ],
        "columns_with_nulls": [n for n, p in schema.items() if p["null_ratio"] > 0],
    }
