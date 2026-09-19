"""Date parsing with an explicit, auditable strategy.

We never guess between DD/MM and MM/DD when both are plausible for a single
value. Instead the *column* is profiled first: if any value in the column is
unambiguously day-first (day > 12) the whole column is treated as day-first.
That makes the conversion deterministic and explainable, and it is why date
normalisation does not need a human.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .text import is_blank

ISO = "%Y-%m-%d"

# Formats that carry no ambiguity at all.
_UNAMBIGUOUS_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d-%B-%Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d.%m.%Y",
    "%Y%m%d",
]

_NUMERIC_RE = re.compile(r"^(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{2,4})$")


class DateParseResult:
    __slots__ = ("value", "format_used", "error")

    def __init__(self, value: date | None, format_used: str | None, error: str | None = None):
        self.value = value
        self.format_used = format_used
        self.error = error

    @property
    def ok(self) -> bool:
        return self.value is not None

    @property
    def iso(self) -> str | None:
        return self.value.isoformat() if self.value else None


def _strip(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _try_formats(text: str) -> DateParseResult | None:
    for fmt in _UNAMBIGUOUS_FORMATS:
        try:
            return DateParseResult(datetime.strptime(text, fmt).date(), fmt)
        except ValueError:
            continue
    return None


def detect_day_first(values: list) -> bool:
    """True when the column is day-first (DD/MM/YYYY).

    Evidence: at least one row whose first component is > 12. Defaults to
    day-first because the source systems in scope are non-US; the decision is
    always recorded in the audit trail.
    """
    month_first_evidence = 0
    for value in values:
        if is_blank(value):
            continue
        m = _NUMERIC_RE.match(_strip(value))
        if not m:
            continue
        a, b, _ = (int(m.group(1)), int(m.group(2)), m.group(3))
        if len(m.group(1)) == 4:
            continue
        if a > 12:
            return True
        if b > 12:
            month_first_evidence += 1
    return month_first_evidence == 0


def parse_date(value, day_first: bool = True) -> DateParseResult:
    if is_blank(value):
        return DateParseResult(None, None, "empty")

    if isinstance(value, datetime):
        return DateParseResult(value.date(), "datetime")
    if isinstance(value, date):
        return DateParseResult(value, "date")

    text = _strip(value)
    # Excel sometimes hands us '1988-08-12 00:00:00'
    if " " in text and text.count("-") == 2:
        text = text.split(" ")[0]

    direct = _try_formats(text)
    if direct:
        return direct

    m = _NUMERIC_RE.match(text)
    if not m:
        return DateParseResult(None, None, f"unrecognised date format: {text!r}")

    a, b, c = m.group(1), m.group(2), m.group(3)
    if len(a) == 4:
        candidates = [(int(a), int(b), int(c))]  # YYYY-M-D
    else:
        year = int(c) if len(c) == 4 else 2000 + int(c) if int(c) < 50 else 1900 + int(c)
        if day_first:
            candidates = [(year, int(b), int(a))]
        else:
            candidates = [(year, int(a), int(b))]

    for y, mo, d in candidates:
        try:
            return DateParseResult(
                date(y, mo, d), "%d/%m/%Y" if day_first else "%m/%d/%Y"
            )
        except ValueError as exc:
            return DateParseResult(None, None, f"invalid calendar date {text!r} ({exc})")
    return DateParseResult(None, None, f"unrecognised date format: {text!r}")


def to_iso(value, day_first: bool = True) -> str | None:
    return parse_date(value, day_first=day_first).iso


def looks_like_date_column(values: list) -> float:
    """Fraction of non-empty values that parse as a date under either order."""
    considered = [v for v in values if not is_blank(v)]
    if not considered:
        return 0.0
    ok = 0
    for v in considered:
        if parse_date(v, day_first=True).ok or parse_date(v, day_first=False).ok:
            ok += 1
    return ok / len(considered)
