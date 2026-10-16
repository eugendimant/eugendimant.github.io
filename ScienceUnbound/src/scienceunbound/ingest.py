"""Read a data file (CSV, TSV, Stata, Excel), handle the Qualtrics three-row header, infer a data dictionary."""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MAX_BYTES = 200 * 1024 * 1024
ROW_ID = "su_row_id"


def _to_bytes(source: Any) -> tuple[bytes, str]:
    if isinstance(source, (str, Path)):
        p = Path(source)
        return p.read_bytes(), p.name
    name = getattr(source, "name", "upload.csv")
    data = source.read() if hasattr(source, "read") else bytes(source)
    return data, name


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    """Blank strings become missing; columns whose non-missing values are all numeric become numeric."""
    out = {}
    for c in df.columns:
        s = df[c]
        if not pd.api.types.is_numeric_dtype(s):
            s = s.astype("string").str.strip().replace("", pd.NA)
            conv = pd.to_numeric(s, errors="coerce")
            if s.notna().sum() > 0 and conv.notna().sum() == s.notna().sum():
                s = conv
            else:
                s = s.astype(object).where(s.notna(), np.nan)
        out[c] = s
    return pd.DataFrame(out)


def _detect_qualtrics(raw: pd.DataFrame) -> bool:
    if len(raw) < 2:
        return False
    row2 = raw.iloc[1].astype(str).tolist()[:12]
    return any("ImportId" in v for v in row2)


def _sniff(data: bytes) -> str:
    head = data[:4096].decode("utf-8-sig", errors="replace").splitlines()[:1]
    line = head[0] if head else ""
    return max([",", ";", "\t", "|"], key=line.count)


def read_table(source: Any, filename: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Return (dataframe, meta). Meta holds the file hash, the Qualtrics question labels and counts. No row values."""
    data, name = _to_bytes(source)
    name = filename or name
    if len(data) > MAX_BYTES:
        raise ValueError(f"file is {len(data) / 1e6:.0f} MB; the limit is {MAX_BYTES // 1_000_000} MB")
    ext = Path(name).suffix.lower()
    meta: dict = {"filename": name, "sha256": hashlib.sha256(data).hexdigest(), "qualtrics": False, "labels": {}}
    if ext in (".csv", ".tsv", ".txt"):
        sep = "\t" if ext == ".tsv" else None
        header = next(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace")), delimiter=sep or _sniff(data)), [])
        dups = sorted({h for h in header if header.count(h) > 1})
        if dups:                      # pandas would silently rename these to 'name.1'
            raise ValueError("duplicate column names: " + ", ".join(dups))
        raw = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, encoding="utf-8-sig",
                          sep=sep, engine="python" if sep is None else "c")
        if _detect_qualtrics(raw):
            meta["qualtrics"] = True
            meta["labels"] = {c: str(raw.iloc[0][c]) for c in raw.columns}
            raw = raw.iloc[2:].reset_index(drop=True)
        df = _coerce(raw)
    elif ext == ".dta":
        df = pd.read_stata(io.BytesIO(data), convert_categoricals=False)
    elif ext in (".xlsx", ".xls"):
        df = _coerce(pd.read_excel(io.BytesIO(data), dtype=str, keep_default_na=False))
    else:
        raise ValueError(f"unsupported file type '{ext}'. Use CSV, TSV, Stata (.dta) or Excel.")
    if df.columns.duplicated().any():
        raise ValueError("duplicate column names: " + ", ".join(sorted(set(df.columns[df.columns.duplicated()]))))
    df.columns = [str(c).strip() for c in df.columns]
    meta["n_rows"], meta["n_cols"] = int(len(df)), int(df.shape[1])
    return df, meta


def infer_dictionary(df: pd.DataFrame, labels: dict | None = None) -> pd.DataFrame:
    """One row per column: kind, distinct count, missing share. Never contains cell values."""
    rows = []
    n = max(len(df), 1)
    for c in df.columns:
        s = df[c]
        nu = int(s.nunique(dropna=True))
        miss = float(s.isna().mean()) if len(df) else 0.0
        if pd.api.types.is_numeric_dtype(s):
            kind = "binary" if nu <= 2 else "numeric"
        elif nu <= 30 or nu / n < 0.05:
            kind = "categorical"
        else:
            kind = "text"
        rows.append({"column": c, "kind": kind, "distinct": nu, "missing_pct": round(100 * miss, 1),
                     "label": (labels or {}).get(c, "")})
    return pd.DataFrame(rows)


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Round-trip through CSV so in-memory frames get exactly the dtypes a re-read of the published file will have."""
    return _coerce(pd.read_csv(io.StringIO(df.to_csv(index=False)), dtype=str, keep_default_na=False))


def frame_sha256(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()
