"""File ingestion: CSV / Excel -> SourceFile + SourceRecord rows.

Intentionally dumb and lossless. Nothing is cleaned here; every value is kept
verbatim as a string so that the audit trail can always show the true "before".
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import settings
from ..utils.errors import UnsupportedFileError, ValidationError
from ..utils.text import is_blank

CSV_EXT = {".csv"}
EXCEL_EXT = {".xlsx", ".xls"}


def _validate_file(path: Path, size_bytes: int) -> str:
    ext = path.suffix.lower()
    if ext not in settings.allowed_extensions:
        raise UnsupportedFileError(
            f"Unsupported file type '{ext}'. Allowed: {sorted(settings.allowed_extensions)}",
            details={"filename": path.name},
        )
    if size_bytes > settings.upload_max_bytes:
        raise ValidationError(
            f"File '{path.name}' is {size_bytes} bytes, limit is {settings.upload_max_bytes}",
            details={"filename": path.name},
        )
    return "csv" if ext in CSV_EXT else "excel"


def read_table(path: Path) -> pd.DataFrame:
    """Read a source file into a DataFrame of raw strings."""
    ext = path.suffix.lower()
    if ext in CSV_EXT:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[])
    elif ext in EXCEL_EXT:
        # openpyxl only; never evaluate formulas or macros from an uploaded file.
        df = pd.read_excel(path, engine="openpyxl", dtype=str, keep_default_na=False, na_values=[])
    else:
        raise UnsupportedFileError(f"Unsupported file type '{ext}'", details={"file": path.name})

    df.columns = [str(c).strip() for c in df.columns]
    return df


def ingest_file(path: Path) -> dict:
    """Return {filename, file_type, size_bytes, columns, rows:[{col: value}]}."""
    path = Path(path)
    if not path.exists():
        raise ValidationError(f"Source file not found: {path}")
    size_bytes = path.stat().st_size
    file_type = _validate_file(path, size_bytes)

    df = read_table(path)
    if df.empty:
        raise ValidationError(f"File '{path.name}' contains no data rows")

    rows: list[dict] = []
    for idx, row in df.iterrows():
        raw = {}
        for col in df.columns:
            value = row[col]
            raw[col] = "" if is_blank(value) else str(value)
        if all(v == "" for v in raw.values()):
            continue  # skip completely empty rows
        rows.append({"row_number": int(idx) + 2, "raw": raw})  # +2 = header + 1-based

    return {
        "filename": path.name,
        "file_type": file_type,
        "size_bytes": size_bytes,
        "columns": list(df.columns),
        "rows": rows,
    }
