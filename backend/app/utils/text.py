"""Deterministic text / name / email / phone normalisation primitives.

These are pure functions with no side effects so they can be unit tested and
so the agent can describe exactly which rule produced a change.
"""
from __future__ import annotations

import re
import unicodedata

WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
DIGITS_RE = re.compile(r"\d")

# Name particles that should not be title-cased like ordinary words.
_LOWER_PARTICLES = {"van", "der", "den", "de", "di", "da", "bin", "binti", "al", "el"}
_UPPER_TOKENS = {"ii", "iii", "iv", "jr", "sr"}


def is_blank(value) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "none", "null", "n/a", "na", "-", "--"}


def collapse_whitespace(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip()


CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def slugify(value: str) -> str:
    """Canonical key for a column name.

    'Emp ID ' -> 'emp id', 'joiningDate' -> 'joining date', 'DOB' -> 'dob'.
    Splitting camelCase matters: it is the difference between an exact alias
    hit and a fuzzy one, which changes whether the agent needs a human.
    """
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    text = CAMEL_RE.sub(" ", text)
    text = NON_ALNUM_RE.sub(" ", text.lower())
    return collapse_whitespace(text)


def tokens(value: str) -> list[str]:
    return [t for t in slugify(value).split(" ") if t]


def normalise_person_name(value: str) -> str:
    """'  JOHN   doe ' -> 'John Doe'. Preserves already mixed-case names."""
    text = collapse_whitespace(str(value))
    if not text:
        return text
    # Only re-case when the input is clearly uniform (all upper / all lower).
    if not (text.isupper() or text.islower()):
        return text
    out = []
    for word in text.split(" "):
        lowered = word.lower()
        if lowered in _UPPER_TOKENS:
            out.append(lowered.upper())
        elif lowered in _LOWER_PARTICLES and out:
            out.append(lowered)
        else:
            out.append("-".join(p.capitalize() for p in lowered.split("-")))
    return " ".join(out)


def normalise_email(value: str) -> str:
    return collapse_whitespace(str(value)).lower()


def is_valid_email(value: str) -> bool:
    """Strict on purpose: surrounding whitespace makes an address INVALID.

    Cleaning removes it deterministically, so a value that still carries
    whitespace by the time validation runs is a signal that something skipped
    the cleaning stage - and it would be sent to the target verbatim.
    """
    return bool(EMAIL_RE.match(str(value)))


def normalise_phone(value, default_country_code: str = "+91") -> str | None:
    """Return E.164-ish '+<cc><number>' or None when it cannot be done safely.

    Deliberately conservative: anything that is not a recognisable 10-digit
    national number or an 11-13 digit international number is left alone for a
    human, rather than being silently mangled.
    """
    if is_blank(value):
        return None
    raw = str(value).strip()
    has_plus = raw.lstrip().startswith("+")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    cc = default_country_code.lstrip("+")
    if has_plus:
        if len(digits) < 10 or len(digits) > 15:
            return None
        return "+" + digits
    if len(digits) == 10:
        return f"+{cc}{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+{cc}{digits[1:]}"
    if len(digits) in (11, 12, 13) and digits.startswith(cc):
        return "+" + digits
    return None


def title_case_label(value: str) -> str:
    """Normalise labels such as departments / designations."""
    text = collapse_whitespace(str(value))
    if not text:
        return text
    if text.isupper() or text.islower():
        return " ".join(w.capitalize() if len(w) > 2 else w.upper() for w in text.split(" "))
    return text


def looks_like_mobile(values: list[str]) -> float:
    """Fraction of sample values that look like personal mobile numbers.

    Used as a *value-level* signal when the column name alone is ambiguous.
    """
    considered = [v for v in values if not is_blank(v)]
    if not considered:
        return 0.0
    hits = 0
    for v in considered:
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        national = digits[-10:]
        if len(national) == 10 and national[0] in "6789":
            hits += 1
    return hits / len(considered)


def looks_like_extension(values: list[str]) -> float:
    """Fraction of sample values that look like short desk extensions."""
    considered = [v for v in values if not is_blank(v)]
    if not considered:
        return 0.0
    hits = 0
    for v in considered:
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        if 0 < len(digits) <= 6:
            hits += 1
    return hits / len(considered)


def looks_like_email(values: list[str]) -> float:
    considered = [v for v in values if not is_blank(v)]
    if not considered:
        return 0.0
    return sum(1 for v in considered if "@" in str(v)) / len(considered)


def mask_pii(value: str | None, keep: int = 2) -> str:
    """Very small helper used when writing potentially sensitive audit values."""
    if value is None:
        return ""
    text = str(value)
    if "@" in text:
        local, _, domain = text.partition("@")
        return f"{local[:keep]}{'*' * max(len(local) - keep, 0)}@{domain}"
    if len(text) <= keep:
        return "*" * len(text)
    return f"{text[:keep]}{'*' * (len(text) - keep)}"


def sanitize_cell(value) -> str:
    """Neutralise CSV/Excel formula injection before a value is shown or stored."""
    if value is None:
        return ""
    text = str(value)
    if text[:1] in ("=", "+", "-", "@") and len(text) > 1 and not DIGITS_RE.match(text[1:2] or ""):
        return "'" + text
    return text
