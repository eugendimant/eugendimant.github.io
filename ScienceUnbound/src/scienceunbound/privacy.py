"""Privacy engine.

Three layers, none of which sends a value anywhere:

1. audit_dataframe   scans EVERY cell of EVERY column (vectorised) for identifiers, free text and timestamps.
                     Reports contain column names, reasons and counts, never cell values.
2. k-anonymity       measures re-identification risk from combinations of ordinary columns (age x zip x gender)
                     and generalises them until every combination is shared by at least k respondents.
3. gate_files        re-scans every file of a finished package before anything is committed.
"""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- patterns
_OCT = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
STRONG = {  # any hit in a column is enough: these never occur in clean survey data
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "ssn": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    "ipv4": re.compile(rf"(?<![\d.]){_OCT}(?:\.{_OCT}){{3}}(?![\d.])"),
    "phone": re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-])?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"),
    "social_profile": re.compile(r"(?:twitter|linkedin|facebook|instagram)\.com/[\w.-]+", re.I),
}
ID_LIKE = {  # recruitment and response ids: flag when most of a column looks like one
    "prolific_id": re.compile(r"^[0-9a-f]{24}$"),
    "mturk_id": re.compile(r"^A(?=[0-9A-Z]*\d)(?=[0-9A-Z]*[B-Z])[0-9A-Z]{11,20}$"),
    "uuid": re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
    "qualtrics_response_id": re.compile(r"^R_[A-Za-z0-9]{10,20}$"),
    "hex32_id": re.compile(r"^[0-9A-Fa-f]{32}$"),
    "ipv6": re.compile(r"^(?=.*:.*:)[0-9a-fA-F:]{7,39}$"),
}
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}")
HEADER_RULES = {
    "email": re.compile(r"e-?mail", re.I),
    "phone": re.compile(r"(^|[_\s])(phone|mobile|cell|tel)($|[_\s])", re.I),
    "ip": re.compile(r"(^|[_\s])ip([_\s]?address)?($|[_\s])", re.I),
    "name": re.compile(r"(^|[_\s])(first|last|full|sur)?[_\s]?name($|[_\s])", re.I),
    "geo": re.compile(r"(latitude|longitude|\bzip|postal|postcode|street|address|\bcity\b|\bcounty\b)", re.I),
    "dob": re.compile(r"(\bdob\b|date[_\s]?of[_\s]?birth|birth[_\s]?date|birthday)", re.I),
    "ssn": re.compile(r"\bssn\b|social[_\s]?security", re.I),
    "participant_id": re.compile(r"(worker|participant|respondent|panel|user|prolific|mturk|turk|subject)[_\s]?(id|code)|^(prolific_)?pid$|^worker$", re.I),
    "device": re.compile(r"user[_\s]?agent|device[_\s]?id|browser[_\s]?id|fingerprint", re.I),
}
KNOWN_ID_COLUMNS = {c.lower() for c in (
    "ResponseId", "IPAddress", "RecipientLastName", "RecipientFirstName", "RecipientEmail", "ExternalReference",
    "LocationLatitude", "LocationLongitude", "participantId", "projectId", "assignmentId", "workerId", "hitId",
    "PROLIFIC_PID", "SESSION_ID", "STUDY_ID", "mTurkCode", "rid", "psid", "caseid")}
TIMESTAMP_COLUMNS = {"startdate", "enddate", "recordeddate"}
SAFE_COLUMNS = {"su_row_id"}

# Share thresholds. Strong identifiers: one hit is a finding. ID-like and timestamps: most of the column.
ID_SHARE = 0.5
PROSE_SHARE = 0.02
HIGH_CARDINALITY = 0.9
_LETTER = re.compile(r"[A-Za-z]")


@dataclass
class Finding:
    column: str
    reason: str
    action: str            # "drop" (removed unless overridden) | "review"
    hits: int = 0
    share: float = 0.0


@dataclass
class PrivacyReport:
    n_rows: int
    n_cols: int
    cells_scanned: int
    findings: list[Finding] = field(default_factory=list)

    def to_drop(self, keep: set[str] | list[str] = ()) -> list[str]:
        keep = set(keep)
        return [f.column for f in self.findings if f.action == "drop" and f.column not in keep]

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame([f.__dict__ for f in self.findings],
                            columns=["column", "reason", "action", "hits", "share"])


def _prose_mask(s: pd.Series) -> pd.Series:
    words = s.str.split().str.len().fillna(0)
    letters = s.str.contains(_LETTER, regex=True, na=False)
    punct = s.str.contains(r"[.?!]", regex=True, na=False)
    return letters & (s.str.contains("\n", regex=False, na=False) | (words >= 8) | ((words >= 5) & punct))


def audit_dataframe(df: pd.DataFrame, closed: set[str] | list[str] = ()) -> PrivacyReport:
    """Scan every cell. `closed` lists columns known to hold closed-ended answers (exempt from the free-text check)."""
    closed = set(closed)
    rep = PrivacyReport(n_rows=len(df), n_cols=df.shape[1], cells_scanned=int(df.size))
    for col in df.columns:
        if col in SAFE_COLUMNS:
            continue
        s = df[col]
        low = str(col).lower()
        reason = None
        action = "drop"
        hits, share = 0, 0.0
        if low in KNOWN_ID_COLUMNS:
            reason = "known identifier column"
        elif low in TIMESTAMP_COLUMNS:
            reason, action = "exact timestamp (a quasi-identifier)", "drop"
        else:
            for code, rx in HEADER_RULES.items():
                if rx.search(str(col)):
                    reason = f"column name suggests {code.replace('_', ' ')}"
                    break
        if reason is None and not pd.api.types.is_numeric_dtype(s):
            t = s.dropna().astype(str)
            t = t[t.str.strip() != ""]
            n = len(t)
            if n:
                for code, rx in STRONG.items():
                    h = int(t.str.contains(rx, regex=True).sum())
                    if h:
                        reason, hits, share = f"contains {code.replace('_', ' ')} values", h, h / n
                        break
                if reason is None:
                    for code, rx in ID_LIKE.items():
                        h = int(t.str.match(rx).sum())
                        if h / n >= ID_SHARE:
                            reason, hits, share = f"looks like {code.replace('_', ' ')}", h, h / n
                            break
                if reason is None:
                    h = int(t.str.match(TIMESTAMP).sum())
                    if h / n >= ID_SHARE:
                        reason, hits, share = "exact timestamps", h, h / n
                if reason is None and col not in closed:
                    h = int(_prose_mask(t).sum())
                    if h and h >= max(1, math.ceil(PROSE_SHARE * n)):
                        reason, hits, share = "free text (may name people or places)", h, h / n
                if reason is None and col not in closed and n >= 30 and t.nunique() / n >= HIGH_CARDINALITY:
                    reason, hits, share = "almost every value is unique (identifier-like)", n, 1.0
        if reason:
            rep.findings.append(Finding(str(col), reason, action, hits, round(share, 4)))
    return rep


# ---------------------------------------------------------------- re-identification risk
def k_anonymity(df: pd.DataFrame, quasi: list[str], k: int = 5) -> dict:
    """Group sizes over the combination of `quasi` columns. Missing counts as a value (it still singles people out)."""
    quasi = [c for c in quasi if c in df.columns]
    if not quasi or df.empty:
        return {"quasi": quasi, "k_target": k, "min_k": None, "rows_below_k": 0, "share_below_k": 0.0,
                "unique_rows": 0, "groups": 0}
    sizes = df.groupby(quasi, dropna=False, observed=True).size()
    per_row = df.groupby(quasi, dropna=False, observed=True)[quasi[0]].transform("size")
    below = int((per_row < k).sum())
    return {"quasi": quasi, "k_target": k, "min_k": int(sizes.min()), "rows_below_k": below,
            "share_below_k": round(below / len(df), 4), "unique_rows": int((per_row == 1).sum()), "groups": int(len(sizes))}


def _generalise_numeric(orig: pd.Series, bins: int) -> pd.Series:
    x = pd.to_numeric(orig, errors="coerce")
    try:
        q = pd.qcut(x, q=bins, duplicates="drop")
    except ValueError:
        return orig.astype(object)
    lab = q.astype(object).map(lambda iv: f"{iv.left:g}-{iv.right:g}" if isinstance(iv, pd.Interval) else np.nan)
    return lab


def enforce_k(df: pd.DataFrame, quasi: list[str], k: int = 5, max_steps: int = 60, allow_drop: bool = False) -> tuple[pd.DataFrame, list[str], dict]:
    """Make every combination of the quasi-identifier columns describe at least k rows, changing as little as possible.

    1. Generalise: numeric columns are re-binned into fewer quantile bands; other columns merge categories rarer than k into 'Other'.
    2. Suppress: rows that still sit in a group below k get '(suppressed)' in the quasi-identifier columns (their other columns stay).
    3. Remove rows only if the suppressed rows themselves number fewer than k.
    Columns are never deleted unless allow_drop=True, because a column the analysis needs would silently break the plan.
    Returns (new frame, actions taken, final stats).
    """
    out = df.copy()
    originals = {c: df[c].copy() for c in quasi if c in df.columns}
    state = {c: {"bins": 12 if pd.api.types.is_numeric_dtype(df[c]) and df[c].nunique() > 8 else None, "stuck": False} for c in originals}
    actions: list[str] = []
    live = list(originals)
    for _ in range(max_steps):
        stats = k_anonymity(out, live, k)
        movable = [c for c in live if not state[c]["stuck"]]
        if stats["min_k"] is None or stats["min_k"] >= k or not movable:
            break
        col = max(movable, key=lambda c: out[c].nunique(dropna=False))
        st = state[col]
        if st["bins"] is not None and st["bins"] > 2:
            st["bins"] = max(2, int(st["bins"] * 0.7))
            out[col] = _generalise_numeric(originals[col], st["bins"])
            actions.append(f"{col}: grouped into {st['bins']} bands")
        elif st["bins"] is None and out[col].astype(str).nunique() > 2:
            vc = out[col].astype(str).value_counts()
            rare = set(vc[vc < k].index)
            if rare:
                out[col] = out[col].astype(object).where(~out[col].astype(str).isin(rare), "Other")
                actions.append(f"{col}: {len(rare)} rare categories merged into 'Other'")
            else:
                st["stuck"] = True
        else:
            st["stuck"] = True
        if st["stuck"] and allow_drop:
            out = out.drop(columns=[col])
            live.remove(col)
            actions.append(f"{col}: removed (could not be generalised enough)")
    stats = k_anonymity(out, live, k)
    if stats["min_k"] is not None and stats["min_k"] < k and live:
        per_row = out.groupby(live, dropna=False, observed=True)[live[0]].transform("size")
        risky = per_row < k
        n_risky = int(risky.sum())
        for c in live:
            out[c] = out[c].astype(object).where(~risky, np.nan)     # missing, never a fake category an analysis could use
        actions.append(f"{n_risky} respondents in rare combinations: quasi-identifier values suppressed (set to missing)")
        stats = k_anonymity(out, live, k)
        if stats["min_k"] is not None and stats["min_k"] < k:
            sup = out[live].isna().all(axis=1)
            actions.append(f"{int(sup.sum())} respondents removed: too few to hide among themselves")
            out = out.loc[~sup].reset_index(drop=True)
            stats = k_anonymity(out, live, k)
    # keep only the last band count per column: "age: 8 bands, 5 bands, 3 bands" reads as noise
    last: dict[str, int] = {}
    for i, a in enumerate(actions):
        if ": grouped into" in a:
            last[a.split(":")[0]] = i
    actions = [a for i, a in enumerate(actions) if ": grouped into" not in a or last[a.split(":")[0]] == i]
    return out, actions, stats


# ---------------------------------------------------------------- package gate
@dataclass
class GateIssue:
    path: str
    problem: str


def scan_text(text: str) -> list[str]:
    probs = []
    for code, rx in STRONG.items():
        if rx.search(text):
            probs.append(f"contains {code.replace('_', ' ')}")
    return probs


def gate_files(files: dict[str, bytes], allow_data: bool = True) -> list[GateIssue]:
    """Final check over the bytes that are about to be committed. An empty list means nothing was found."""
    issues: list[GateIssue] = []
    for path, blob in sorted(files.items()):
        low = path.lower()
        if low.endswith((".png", ".jpg", ".jpeg", ".svg", ".pdf", ".zip")):
            continue
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(GateIssue(path, "binary file with an unknown type"))
            continue
        if low.endswith(".csv"):
            try:
                df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
            except Exception as e:  # unreadable csv is itself suspicious
                issues.append(GateIssue(path, f"unreadable CSV ({e.__class__.__name__})"))
                continue
            df = df.replace("", np.nan)
            conv = {c: pd.to_numeric(df[c], errors="coerce") if df[c].dropna().map(lambda v: _is_num(v)).all() else df[c]
                    for c in df.columns}
            df = pd.DataFrame(conv)
            if low.startswith("data/"):
                if not allow_data:
                    issues.append(GateIssue(path, "respondent-level data is not allowed in this package"))
                    continue
                for f in audit_dataframe(df).findings:
                    if f.action == "drop":
                        issues.append(GateIssue(path, f"column '{f.column}': {f.reason}"))
            else:
                if len(df) > 5000:
                    issues.append(GateIssue(path, f"{len(df)} rows in a results table: looks like respondent-level data"))
                for f in audit_dataframe(df).findings:
                    if f.reason.startswith(("contains", "looks like")):
                        issues.append(GateIssue(path, f"column '{f.column}': {f.reason}"))
        else:
            for pr in scan_text(text):
                issues.append(GateIssue(path, pr))
    return issues


def _is_num(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False
