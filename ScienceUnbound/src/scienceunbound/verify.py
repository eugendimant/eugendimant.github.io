"""Independent verification of a report against its result tables.

This module shares no code with report.py. It rebuilds the set of admissible numbers from the result tables and checks:

1. every number in the prose is one of them (to the precision it is printed at);
2. every table row and result line that names an analysis carries that analysis's own numbers (catches swapped numbers);
3. every estimate in effects.csv is reported (catches omitted, inconvenient results).

It also works on text a language model has edited, because it only reads the finished report.
"""
from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import pandas as pd

VERIF_RE = re.compile(r"<!-- su:verification:start -->.*?<!-- su:verification:end -->", re.S)
AUTHOR_RE = re.compile(r"<!-- su:author -->.*?<!-- su:/author -->", re.S)
_STRIP = [
    AUTHOR_RE,
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"```.*?```", re.S),
    re.compile(r"`[^`\n]*`"),
    re.compile(r"!?\[[^\]]*\]\([^)]*\)"),
    re.compile(r"https?://\S+"),
    re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?"),
    re.compile(r"\b\d+\.\d+\.\d+(?:\.\d+)?\b"),
    re.compile(r"SHA-?256"),
    re.compile(r"CC[ -]BY[ -]\d\.\d"),
]
NUM = re.compile(r"(?<![\w.])(?:[−\-])?(?:\d{1,3}(?:,\d{3})+|\d*\.\d+|\d+)(?![\w])")
MINUS = "−"
ROW_STRICT = {"confirmatory results", "exploratory results", "robustness", "what a follow-up would need"}
P_CELL = re.compile(r"^(<)?\s*(\d*\.\d+|\d+)$")
EFF_CELL = re.compile(r"^\s*([−\-]?[\d.]+) \[([−\-]?[\d.]+), ([−\-]?[\d.]+)\]\s*$")
LINE_ID = re.compile(r"^\s*(?:[-*]\s+)?\*\*([A-Za-z][A-Za-z0-9_:\-.]*)\*\*")
LINE_EFF = re.compile(r"(?:g \(interaction\)|g|r) = ([−\-]?[\d.]+) \[([−\-]?[\d.]+), ([−\-]?[\d.]+)\]")
LINE_P = re.compile(r"(?<!adjusted )(?<!test )\bp (=|<) (1\.000|\.\d{3})")
LINE_PADJ = re.compile(r"adjusted p (=|<) (1\.000|\.\d{3})")
LINE_N = re.compile(r"\bN = (\d+)")


def _f(x: str) -> float:
    return float(x.replace(MINUS, "-").replace(",", ""))


def _decimals(tok: str) -> int:
    tok = tok.replace(",", "")
    return len(tok.split(".")[1]) if "." in tok else 0


def _strip_text(md: str) -> str:
    md = VERIF_RE.sub("", md)
    for rx in _STRIP:
        md = rx.sub(" ", md)
    return md


def _collect(obj: Any, out: list[float]) -> None:
    if isinstance(obj, pd.DataFrame):
        for c in obj.columns:
            if pd.api.types.is_numeric_dtype(obj[c]) or obj[c].dtype == bool:
                out.extend(float(v) for v in obj[c].dropna().astype(float).tolist() if math.isfinite(float(v)))
            else:
                for v in obj[c].dropna().tolist():
                    _collect(v, out)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, out)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float, np.integer, np.floating)):
        if math.isfinite(float(obj)):
            out.append(float(obj))


def derived_counts(eff: pd.DataFrame) -> list[float]:
    """Counts a reader may state about the table itself, computed here and not taken from the writer."""
    out = [float(len(eff))]
    for col in ("verdict", "tag", "confirmatory", "hypothesis", "outcome", "adj_method", "es_metric"):
        if col in eff.columns:
            out += [float(v) for v in eff[col].value_counts().values]
    conf = eff[eff["confirmatory"].astype(bool)] if "confirmatory" in eff.columns else eff
    out += [float(len(conf)), float(len(eff) - len(conf))]
    for col in ("verdict", "tag"):
        if col in conf.columns:
            out += [float(v) for v in conf[col].value_counts().values]
    return out


def _table_counts(df: Any) -> list[float]:
    if not isinstance(df, pd.DataFrame):
        return []
    out = [float(len(df))]
    for c in df.columns:
        if str(c) in ("p", "p_adj") and pd.api.types.is_numeric_dtype(df[c]):
            out += [float((df[c] < 0.05).sum()), float((df[c] < 0.01).sum())]
    return out


def _consts(plan: dict) -> list[float]:
    alpha = float(plan.get("alpha", 0.05))
    return [alpha, 1 - alpha, round(100 * (1 - alpha)), 100 * alpha, 0.80, 80, 90, 0.001, 0.0, 5.0 if alpha == 0.05 else 100 * alpha]


def build_pools(eff: pd.DataFrame, tables: dict[str, Any], plan: dict, extras: list[float] | None) -> dict:
    """Per-section and per-analysis pools of admissible numbers. A number must come from the pool of the place it is printed."""
    const = _consts(plan)
    counts = derived_counts(eff) + [float(len(plan.get("hypotheses", []))), float(len(plan.get("outcomes", [])))]
    row_pool: dict[str, list[float]] = {}
    for r in eff.to_dict("records"):
        row_pool.setdefault(r["analysis_id"], [])
        _collect({k: v for k, v in r.items() if not isinstance(v, str)}, row_pool[r["analysis_id"]])
    for name in ("spec_summary", "followups"):
        df = tables.get(name)
        if isinstance(df, pd.DataFrame) and "analysis_id" in df.columns:
            for aid, g in df.groupby("analysis_id"):
                row_pool.setdefault(aid, [])
                _collect(g.drop(columns=["analysis_id"]), row_pool[aid])
    for h in plan.get("hypotheses", []):
        if h.get("sesoi"):
            const.append(float(h["sesoi"]))
    flow, srm, info = [], [], []
    _collect(tables.get("flow"), flow)
    _collect(tables.get("srm"), srm)
    _collect(tables.get("outcome_info"), info)
    bal, att, warn = [], [], []
    _collect(tables.get("balance"), bal)
    _collect(tables.get("attrition"), att)
    for w in tables.get("warnings", []) or []:
        warn += [abs(_f(m.group(0))) for m in NUM.finditer(w)]
    eff_n: list[float] = []
    _collect(eff[["n", "n_reference", "n_level"]] if len(eff) else eff, eff_n)
    ex = list(extras or [])
    arms = [float(len(tables.get("srm", {}).get("counts", {})))]
    sections = {
        "": const,
        "summary": const + counts + flow + eff_n,
        "design and sample": const + flow + srm + info + arms + counts,
        "plan and registration status": const + counts,
        "confirmatory results": const + counts,
        "exploratory results": const + counts,
        "robustness": const + counts + _table_counts(tables.get("spec_summary")),
        "design checks": const + srm + bal + att + warn + counts + _table_counts(tables.get("balance")),
        "what a follow-up would need": const + counts,
        "limitations": const + counts,
        "privacy and data": const + ex,
        "provenance and reproducibility": const + [float(plan.get("seed", 0))],
        "how to cite": const, "credits": const,
    }
    return {"rows": row_pool, "sections": sections, "const": const}


def _arr(vals: list[float]) -> np.ndarray:
    a = np.abs(np.asarray(vals, float))
    a = np.concatenate([a, a[(a >= 0) & (a <= 1)] * 100])       # shares printed as percentages
    return np.unique(a[np.isfinite(a)])


def _section_key(heading: str, sections: dict) -> str:
    h = re.sub(r"\(.*?\)", "", heading.lower()).strip(" :")
    h = re.sub(r"\s+[\u2014-].*$", "", h)
    for k in sections:
        if k and h.startswith(k):
            return k
    return "summary" if h == "summary" else ""


def _ok(tok: str, adm: np.ndarray) -> bool:
    v = abs(_f(tok))
    tol = 0.5 * 10 ** (-_decimals(tok)) + 1e-9
    i = np.searchsorted(adm, v - tol, "left")
    return bool(i < len(adm) and adm[i] <= v + tol)


def _close(printed: float, actual: float, dec: int) -> bool:
    return abs(printed - actual) <= 0.5 * 10 ** (-dec) + 1e-9


def _check_p(cell_sign: str | None, cell: str, actual: float) -> bool:
    dec = _decimals(cell)
    v = float(cell)
    if cell_sign == "<":
        return actual < v + 1e-12
    return _close(v, actual, dec)


def _row_by_id(eff: pd.DataFrame) -> dict[str, dict]:
    return {r["analysis_id"]: r for r in eff.to_dict("records")}


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def verify_report(md: str, effects: pd.DataFrame, tables: dict[str, Any], plan: dict, extras: list[float] | None = None) -> dict:
    body = VERIF_RE.sub("", md)
    rows = _row_by_id(effects)
    pools = build_pools(effects, tables, plan, extras)
    sec_arrays = {k: _arr(v) for k, v in pools["sections"].items()}
    row_arrays: dict[str, np.ndarray] = {}
    const_arr = _arr(pools["const"])
    ids = sorted(rows, key=len, reverse=True)
    id_res = {aid: re.compile(re.escape(aid) + r"(?![\w:])") for aid in ids}
    unmatched, checked = [], 0
    section = ""
    for lineno, raw in enumerate(VERIF_RE.sub("", md).splitlines(), 1):
        if raw.startswith("# "):
            continue                                                   # the title is author text
        if raw.startswith("## "):
            section = _section_key(raw[3:], pools["sections"])
            continue
        line = _strip_text(raw)
        if line.strip().startswith("|---") or set(line.strip()) <= set("|- "):
            continue
        present = [a for a in ids if id_res[a].search(line)]
        if present:
            arr = const_arr if section in ROW_STRICT else np.union1d(const_arr, sec_arrays.get(section, sec_arrays[""]))
            for a in present:
                if a not in row_arrays:
                    row_arrays[a] = _arr(pools["rows"].get(a, []))
                arr = np.union1d(arr, row_arrays[a])
        else:
            arr = sec_arrays.get(section, sec_arrays[""])
        for m in NUM.finditer(line):
            tok = m.group(0)
            checked += 1
            if not _ok(tok, arr):
                unmatched.append({"line": lineno, "number": tok, "section": section or "header", "context": line.strip()[:140]})
    # ---- layer 2: rows and result lines carry their own analysis's numbers
    mismatches: list[dict] = []
    seen: set[str] = set()
    header: list[str] | None = None
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("|") and header is None and "Analysis" in s and "Effect size" in s:
            header = _split_row(s)
            continue
        if header is not None:
            if s.startswith("|---") or set(s) <= set("|- "):
                continue
            if not s.startswith("|"):
                header = None
            else:
                cells = _split_row(s)
                aid = cells[0].strip("*` ")
                if aid in rows and len(cells) == len(header):
                    seen.add(aid)
                    r = rows[aid]
                    for h, c in zip(header, cells):
                        if h == "N" and c.isdigit() and int(c) != int(r["n"]):
                            mismatches.append({"analysis_id": aid, "field": "N", "printed": c, "actual": int(r["n"])})
                        elif h == "Estimate":
                            try:
                                if not _close(_f(c), float(r["estimate"]), _decimals(c)):
                                    mismatches.append({"analysis_id": aid, "field": "estimate", "printed": c, "actual": float(r["estimate"])})
                            except ValueError:
                                pass
                        elif h.startswith("Effect size"):
                            m = EFF_CELL.match(c)
                            if m:
                                for k, key in zip(m.groups(), ("es", "es_ci_low", "es_ci_high")):
                                    if not _close(_f(k), float(r[key]), _decimals(k)):
                                        mismatches.append({"analysis_id": aid, "field": key, "printed": k, "actual": float(r[key])})
                        elif h in ("p", "p (adj.)"):
                            m = P_CELL.match(c.replace(" ", " "))
                            if m:
                                key = "p_test" if h == "p" else "p_adj"
                                if not _check_p(m.group(1), m.group(2), float(r[key])):
                                    mismatches.append({"analysis_id": aid, "field": key, "printed": c, "actual": float(r[key])})
                continue
        m = LINE_ID.match(line)
        if m and m.group(1) in rows:
            aid = m.group(1)
            seen.add(aid)
            r = rows[aid]
            e = LINE_EFF.search(line)
            if e:
                for k, key in zip(e.groups(), ("es", "es_ci_low", "es_ci_high")):
                    if not _close(_f(k), float(r[key]), _decimals(k)):
                        mismatches.append({"analysis_id": aid, "field": key, "printed": k, "actual": float(r[key])})
            for rx, key in ((LINE_P, "p_test"), (LINE_PADJ, "p_adj")):
                pm = rx.search(line)
                if pm and not _check_p(pm.group(1) if pm.group(1) == "<" else None, pm.group(2), float(r[key])):
                    mismatches.append({"analysis_id": aid, "field": key, "printed": pm.group(0), "actual": float(r[key])})
            nm = LINE_N.search(line)
            if nm and int(nm.group(1)) != int(r["n"]):
                mismatches.append({"analysis_id": aid, "field": "N", "printed": nm.group(1), "actual": int(r["n"])})
    missing = sorted(set(rows) - seen)
    ok = not unmatched and not mismatches and not missing
    return {"ok": ok, "numbers_checked": checked, "unmatched": unmatched, "row_mismatches": mismatches,
            "estimates_total": len(rows), "estimates_reported": len(seen & set(rows)), "estimates_missing": missing}


def verification_block(v: dict) -> str:
    status = "PASSED" if v["ok"] else "FAILED"
    line = (f"**Numbers verified: {status}.** {v['numbers_checked']} numbers in the text were checked against the result tables by an "
            f"independent script; {len(v['unmatched'])} did not match. {v['estimates_reported']} of {v['estimates_total']} "
            f"estimates are reported; {len(v['row_mismatches'])} table or result-line entries disagree with their source row.")
    return line
