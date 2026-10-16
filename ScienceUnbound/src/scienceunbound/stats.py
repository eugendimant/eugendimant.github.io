"""Estimation. Pure functions over DataFrames; no model calls, no eval.

Effect-size metrics (chosen so that studies can be pooled):
  g      Hedges' g for a contrast between two groups: adjusted difference / pooled raw SD, small-sample corrected.
  r      partial correlation for a continuous predictor; its standard error is for Fisher's z (atanh r).
  g_int  interaction coefficient / pooled raw SD. Reported, never pooled.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as sps
from statsmodels.stats.multitest import multipletests

from .schema import Exclusion, Hypothesis, Outcome, Plan, canon_level

POWER = 0.80
ROW_COLUMNS = [
    "analysis_id", "hypothesis", "label", "construct", "confirmatory", "outcome", "predictor", "contrast", "reference",
    "level", "moderator", "n", "n_reference", "n_level", "n_missing_dropped", "mean_reference", "mean_level",
    "estimate", "se", "df", "ci_low", "ci_high", "p", "p_test", "es_metric", "es", "es_se", "es_ci_low", "es_ci_high",
    "sd_pooled", "mde_raw", "mde_es", "sesoi", "tost_p", "direction", "cov_type", "covariates", "cluster", "formula",
    "p_adj", "adj_method", "verdict", "tag", "note",
]


# ------------------------------------------------------------------ data preparation
def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def cronbach_alpha(items: pd.DataFrame) -> float | None:
    x = items.dropna()
    k = x.shape[1]
    if k < 2 or len(x) < 3:
        return None
    tot = x.sum(axis=1).var(ddof=1)
    if not tot or tot <= 0:
        return None
    return float(k / (k - 1) * (1 - x.var(ddof=1).sum() / tot))


def apply_exclusions(df: pd.DataFrame, exclusions: list[Exclusion]) -> tuple[pd.DataFrame, list[dict]]:
    """Remove rows where each condition is true, in order. Returns (frame, flow) with one flow row per step."""
    flow = [{"step": "Rows in the file", "removed": 0, "remaining": int(len(df))}]
    for e in exclusions:
        col = df[e.column]
        if e.op in ("isna", "notna"):
            hit = col.isna() if e.op == "isna" else col.notna()
        elif e.op in ("in", "not_in"):
            vals = e.value if isinstance(e.value, (list, tuple, set)) else [e.value]
            want = {canon_level(v) for v in vals}
            hit = col.map(canon_level).isin(want)
            hit = hit if e.op == "in" else ~hit & col.notna()
        elif e.op in ("==", "!="):
            eq = col.map(canon_level) == canon_level(e.value)
            hit = eq if e.op == "==" else (~eq) & col.notna()
        else:
            x = _num(col)
            v = float(e.value)
            hit = {">": x > v, ">=": x >= v, "<": x < v, "<=": x <= v}[e.op].fillna(False)
        before = len(df)
        df = df.loc[~hit].copy()
        flow.append({"step": e.reason or f"Excluded where {e.column} {e.op} {'' if e.value is None else e.value}",
                     "removed": int(before - len(df)), "remaining": int(len(df))})
    return df.reset_index(drop=True), flow


def construct_outcomes(df: pd.DataFrame, outcomes: list[Outcome]) -> tuple[pd.DataFrame, dict, list[str]]:
    """Add one numeric column per outcome. Indices are item means and need every item present. Returns (frame, info, warnings)."""
    df = df.copy()
    info: dict[str, dict] = {}
    warns: list[str] = []
    for o in outcomes:
        cols = []
        for it in o.items:
            x = _num(df[it])
            lost = int(df[it].notna().sum() - x.notna().sum())
            if lost:
                warns.append(f"{o.name}: {lost} non-numeric value(s) in '{it}' were treated as missing")
            if it in o.reverse and o.scale:
                x = (o.scale[0] + o.scale[1]) - x
            cols.append(x.rename(it))
        M = pd.concat(cols, axis=1)
        y = M.iloc[:, 0] if o.kind == "single" else M.mean(axis=1, skipna=False)
        df[o.name] = y
        a = cronbach_alpha(M) if o.kind == "index" else None
        info[o.name] = {"kind": o.kind, "n_items": len(o.items), "alpha": None if a is None else round(a, 3),
                        "n_valid": int(y.notna().sum()), "mean": float(y.mean()), "sd": float(y.std(ddof=1))}
        if a is not None and a < 0.6:
            warns.append(f"{o.name}: Cronbach's alpha is {a:.2f}; the index may not measure one construct")
    return df, info, warns


# ------------------------------------------------------------------ small statistics
def hedges_j(n_total: int) -> float:
    dfree = n_total - 2
    return 1 - 3 / (4 * dfree - 1) if dfree > 1 else 1.0


def holm(p: np.ndarray) -> np.ndarray:
    return multipletests(p, method="holm")[1]


def bh(p: np.ndarray) -> np.ndarray:
    return multipletests(p, method="fdr_bh")[1]


def adjust(p: list[float], method: str) -> list[float]:
    arr = np.asarray(p, dtype=float)
    ok = np.isfinite(arr)
    out = arr.copy()
    if method == "none" or ok.sum() == 0:
        return out.tolist()
    out[ok] = holm(arr[ok]) if method == "holm" else bh(arr[ok])
    return out.tolist()


def tost_p(est: float, se: float, df: float, delta: float) -> float:
    """Two one-sided tests: p that the true effect lies inside (-delta, +delta). Small p = equivalence."""
    if not (se > 0 and delta > 0):
        return float("nan")
    p_lo = 1 - sps.t.cdf((est + delta) / se, df)
    p_hi = sps.t.cdf((est - delta) / se, df)
    return float(max(p_lo, p_hi))


def n_per_group(es: float, alpha: float = 0.05, power: float = POWER, metric: str = "g") -> int | None:
    """Sample size per group (two-sample, equal allocation, normal approximation) or total n for a correlation."""
    if not es or not math.isfinite(es) or es == 0:
        return None
    za, zb = sps.norm.ppf(1 - alpha / 2), sps.norm.ppf(power)
    if metric == "r":
        z = math.atanh(min(abs(es), 0.999))
        return int(math.ceil(((za + zb) / z) ** 2 + 3))
    return int(math.ceil(2 * ((za + zb) / abs(es)) ** 2))


# ------------------------------------------------------------------ regression
def _covariate_matrix(sub: pd.DataFrame, covariates: list[str]) -> pd.DataFrame:
    parts = []
    for c in covariates:
        s = sub[c]
        if pd.api.types.is_numeric_dtype(s):
            parts.append(s.astype(float).rename(c))
        else:
            d = pd.get_dummies(s.astype("string"), prefix=c, drop_first=True, dtype=float)
            d.loc[s.isna(), :] = np.nan          # a missing category is missing, not the reference level
            parts.append(d)
    return pd.concat(parts, axis=1) if parts else pd.DataFrame(index=sub.index)


def _full_rank(X: pd.DataFrame, protect: set[str]) -> tuple[pd.DataFrame, list[str]]:
    """Drop constant and collinear covariate columns (never the protected ones)."""
    dropped: list[str] = []
    for c in list(X.columns):
        if c != "const" and c not in protect and X[c].nunique() <= 1:
            X = X.drop(columns=[c])
            dropped.append(c)
    while np.linalg.matrix_rank(X.to_numpy(float)) < X.shape[1]:
        cand = [c for c in X.columns[::-1] if c != "const" and c not in protect]
        if not cand:
            break
        X = X.drop(columns=[cand[0]])
        dropped.append(cand[0])
    return X, dropped


def wmean(y: np.ndarray, w: np.ndarray | None) -> float:
    return float(np.mean(y)) if w is None else float(np.average(y, weights=w))


def wvar(y: np.ndarray, w: np.ndarray | None) -> float:
    """Variance with reliability weights (equals the ordinary sample variance when all weights are equal)."""
    y = np.asarray(y, float)
    if w is None:
        return float(np.var(y, ddof=1))
    m = np.average(y, weights=w)
    denom = w.sum() - (w**2).sum() / w.sum()
    return float((w * (y - m) ** 2).sum() / denom)


def fit(y: np.ndarray, X: pd.DataFrame, se_type: str, groups: np.ndarray | None, weights: np.ndarray | None = None) -> tuple[Any, float]:
    model = sm.OLS(np.asarray(y, float), X) if weights is None else sm.WLS(np.asarray(y, float), X, weights=np.asarray(weights, float))
    if se_type == "cluster":
        res = model.fit(cov_type="cluster", cov_kwds={"groups": groups})
        dof = float(len(np.unique(groups)) - 1)
    else:
        res = model.fit() if se_type == "classical" else model.fit(cov_type=se_type)
        dof = float(res.df_resid)
    return res, dof


def _inference(b: float, se: float, dof: float, alpha: float) -> dict:
    t = b / se if se > 0 else float("nan")
    p = float(2 * sps.t.sf(abs(t), dof)) if math.isfinite(t) else float("nan")
    tc = sps.t.ppf(1 - alpha / 2, dof)
    return {"t": t, "p": p, "ci_low": b - tc * se, "ci_high": b + tc * se}


def _directional_p(p: float, est: float, direction: str) -> float:
    if direction == "two_sided" or not math.isfinite(p):
        return p
    want = 1 if direction == "positive" else -1
    return p / 2 if est * want >= 0 else 1 - p / 2


def _base_row(plan: Plan, h: Hypothesis) -> dict:
    row = {c: np.nan for c in ROW_COLUMNS}
    row.update({"hypothesis": h.id, "label": h.label, "construct": h.construct, "confirmatory": bool(h.confirmatory),
                "outcome": h.outcome, "predictor": h.predictor or plan.arm_column, "moderator": h.moderator,
                "direction": h.direction, "cov_type": h.se, "covariates": ", ".join(h.covariates),
                "cluster": h.cluster, "sesoi": h.sesoi, "note": ("weighted: " + h.weights) if h.weights else ""})
    return row


def _prepare(sub: pd.DataFrame, h: Hypothesis, cols_x: pd.DataFrame, y: pd.Series, extra_missing: pd.Series | None = None):
    """Listwise deletion over outcome, design columns and cluster id; returns aligned arrays and the count dropped."""
    X = cols_x.copy()
    valid = y.notna() & X.notna().all(axis=1)
    if h.se == "cluster":
        valid &= sub[h.cluster].notna()
    if extra_missing is not None:
        valid &= ~extra_missing
    dropped = int((~valid).sum())
    groups = None
    if h.se == "cluster":
        groups = pd.factorize(sub.loc[valid, h.cluster])[0]
    return X.loc[valid], y.loc[valid], groups, valid, dropped


def _contrast(sub: pd.DataFrame, plan: Plan, h: Hypothesis, pred: str, ref: str, lvl: str, alpha: float, note0: str = "") -> dict | None:
    row = _base_row(plan, h)
    codes = sub[pred].map(canon_level)
    two = sub.loc[(codes == ref) | (codes == lvl)].reset_index(drop=True)
    treat = (codes.loc[(codes == ref) | (codes == lvl)].reset_index(drop=True) == lvl).astype(float)
    y = two[h.outcome].astype(float)
    mod_cols = pd.DataFrame(index=two.index)
    mod_names: list[str] = []
    mod_ref = ""
    if h.moderator:
        m = two[h.moderator]
        if pd.api.types.is_numeric_dtype(m) and m.nunique() > 6:
            mc = (m.astype(float) - m.astype(float).mean()).rename(h.moderator)
            mod_cols[mc.name] = mc
            mod_names = [mc.name]
            mod_ref = "per unit"
        else:
            d = pd.get_dummies(m.map(canon_level).where(m.notna()), prefix=h.moderator, dtype=float)
            ref_m = d.sum().idxmax()                        # most common level is the moderator's reference
            mod_ref = ref_m.split("_", 1)[-1] if ref_m.startswith(h.moderator + "_") else ref_m
            d = d.drop(columns=[ref_m])
            d.loc[m.isna(), :] = np.nan
            mod_cols = d
            mod_names = list(d.columns)
    X = pd.DataFrame({"const": 1.0, "treat": treat}, index=two.index)
    if h.moderator:
        X = pd.concat([X, mod_cols], axis=1)
        for mn in mod_names:
            X[f"treat:{mn}"] = X["treat"] * X[mn]
    cov = _covariate_matrix(two, h.covariates)
    X = pd.concat([X, cov], axis=1)
    wser = two[h.weights].astype(float) if h.weights else None
    bad_w = ~(wser.notna() & (wser > 0)) if wser is not None else None
    Xv, yv, groups, valid, dropped = _prepare(two, h, X, y, extra_missing=bad_w)
    wv = wser.loc[Xv.index].to_numpy() if wser is not None else None
    n0, n1 = int((Xv["treat"] == 0).sum()), int((Xv["treat"] == 1).sum())
    if n0 < 3 or n1 < 3:
        return None
    protect = {"const", "treat"} | set(mod_names) | {f"treat:{m}" for m in mod_names}
    Xv, dropped_cols = _full_rank(Xv, protect)
    res, dof = fit(yv.to_numpy(), Xv, h.se, groups, wv)
    m0, m1 = (Xv["treat"] == 0).to_numpy(), (Xv["treat"] == 1).to_numpy()
    s0, s1 = yv.to_numpy()[m0], yv.to_numpy()[m1]
    w0, w1 = (wv[m0], wv[m1]) if wv is not None else (None, None)
    sd_pool = math.sqrt(((n0 - 1) * wvar(s0, w0) + (n1 - 1) * wvar(s1, w1)) / (n0 + n1 - 2))
    J = hedges_j(n0 + n1)
    zc = sps.norm.ppf(1 - alpha / 2) + sps.norm.ppf(POWER)
    targets = [("treat", None)] if not h.moderator else [(f"treat:{mn}", mn) for mn in mod_names]
    rows = []
    for term, mn in targets:
        if term not in res.params.index:
            continue
        r = dict(row)
        b, se = float(res.params[term]), float(res.bse[term])
        inf = _inference(b, se, dof, alpha)
        base = f"{plan.arm_labels.get(lvl) or lvl} vs {plan.arm_labels.get(ref) or ref}"
        if mn is not None:
            lab = mn.split("_", 1)[-1] if mn.startswith(h.moderator + "_") else mn
            base += f", difference by {h.moderator}: " + (f"{lab} vs {mod_ref}" if mod_ref != "per unit" else "per unit")
        r.update({"contrast": base,
                  "reference": ref, "level": lvl, "n": n0 + n1, "n_reference": n0, "n_level": n1,
                  "n_missing_dropped": dropped, "mean_reference": wmean(s0, w0), "mean_level": wmean(s1, w1),
                  "estimate": b, "se": se, "df": dof, "ci_low": inf["ci_low"], "ci_high": inf["ci_high"], "p": inf["p"],
                  "sd_pooled": sd_pool, "mde_raw": zc * se, "mde_es": zc * se / sd_pool * J})
        if mn is None:
            r.update({"es_metric": "g", "es": b / sd_pool * J, "es_se": se / sd_pool * J,
                      "es_ci_low": inf["ci_low"] / sd_pool * J, "es_ci_high": inf["ci_high"] / sd_pool * J})
            if h.sesoi:
                r["tost_p"] = tost_p(b, se, dof, h.sesoi * sd_pool / J)
        else:
            r.update({"es_metric": "g_int", "es": b / sd_pool * J, "es_se": se / sd_pool * J,
                      "es_ci_low": inf["ci_low"] / sd_pool * J, "es_ci_high": inf["ci_high"] / sd_pool * J,
                      "moderator": f"{h.moderator} ({mn})"})
        r["analysis_id"] = f"{h.id}:{lvl}" if mn is None else f"{h.id}:{lvl}_x_{mn}"
        r["p_test"] = _directional_p(inf["p"], b, h.direction)
        r["formula"] = "outcome ~ " + " + ".join([c for c in Xv.columns if c != "const"])
        notes = [x for x in (note0, row["note"]) if x]
        if dropped_cols:
            notes.append("dropped collinear or constant terms: " + ", ".join(dropped_cols))
        if h.se == "cluster" and groups is not None and len(np.unique(groups)) < 30:
            notes.append(f"only {len(np.unique(groups))} clusters: cluster-robust errors are unreliable")
        r["note"] = "; ".join(notes)
        rows.append(r)
    return rows or None


def _continuous(df: pd.DataFrame, plan: Plan, h: Hypothesis, pred: str, alpha: float) -> list[dict]:
    row = _base_row(plan, h)
    x = _num(df[pred])
    y = df[h.outcome].astype(float)
    X = pd.concat([pd.DataFrame({"const": 1.0, "x": x}, index=df.index), _covariate_matrix(df, h.covariates)], axis=1)
    wser = df[h.weights].astype(float) if h.weights else None
    bad_w = ~(wser.notna() & (wser > 0)) if wser is not None else None
    Xv, yv, groups, valid, dropped = _prepare(df, h, X, y, extra_missing=bad_w)
    if len(yv) < 10:
        return []
    Xv, dropped_cols = _full_rank(Xv, {"const", "x"})
    res, dof = fit(yv.to_numpy(), Xv, h.se, groups, wser.loc[Xv.index].to_numpy() if wser is not None else None)
    b, se = float(res.params["x"]), float(res.bse["x"])
    inf = _inference(b, se, dof, alpha)
    t = inf["t"]
    r_p = t / math.sqrt(t * t + dof)
    se_z = 1 / math.sqrt(max(dof - 1, 1))
    z = math.atanh(max(min(r_p, 0.999999), -0.999999))
    zc = sps.norm.ppf(1 - alpha / 2)
    mde_z = (zc + sps.norm.ppf(POWER)) * se_z
    row.update({"contrast": f"per unit of {pred}", "n": len(yv), "n_missing_dropped": dropped, "estimate": b, "se": se,
                "df": dof, "ci_low": inf["ci_low"], "ci_high": inf["ci_high"], "p": inf["p"], "es_metric": "r",
                "es": r_p, "es_se": se_z, "es_ci_low": math.tanh(z - zc * se_z), "es_ci_high": math.tanh(z + zc * se_z),
                "sd_pooled": math.sqrt(wvar(yv.to_numpy(), wser.loc[Xv.index].to_numpy() if wser is not None else None)), "mde_raw": (zc + sps.norm.ppf(POWER)) * se, "mde_es": math.tanh(mde_z)})
    if h.sesoi:
        d = math.atanh(min(h.sesoi, 0.999))
        row["tost_p"] = float(max(1 - sps.norm.cdf((z + d) / se_z), sps.norm.cdf((z - d) / se_z)))
    row["analysis_id"] = h.id
    row["p_test"] = _directional_p(inf["p"], b, h.direction)
    row["formula"] = "outcome ~ " + " + ".join([c for c in Xv.columns if c != "const"])
    notes = [row["note"]] if row["note"] else []
    if dropped_cols:
        notes.append("dropped collinear or constant terms: " + ", ".join(dropped_cols))
    row["note"] = "; ".join(notes)
    return [row]


def estimate_hypothesis(df: pd.DataFrame, plan: Plan, h: Hypothesis, alpha: float | None = None) -> list[dict]:
    alpha = alpha or plan.alpha
    pred = h.predictor or plan.arm_column
    if h.predictor_type == "continuous":
        return _continuous(df, plan, h, pred, alpha)
    ref = canon_level(h.reference or plan.control_level)
    codes = df[pred].map(canon_level)
    present = sorted({c for c in codes.unique() if c and c != ref})
    levels = [canon_level(v) for v in h.levels] if h.levels else present
    rows: list[dict] = []
    for lvl in levels:
        if lvl not in set(codes.unique()):
            continue
        out = _contrast(df, plan, h, pred, ref, lvl, alpha)
        if out:
            rows.extend(out)
    return rows


# ------------------------------------------------------------------ verdicts
def verdict(row: dict, alpha: float) -> str:
    p_adj = row.get("p_adj", float("nan"))
    if isinstance(p_adj, float) and math.isfinite(p_adj) and p_adj < alpha:
        return "supported"
    d, est = row.get("direction", "two_sided"), row.get("estimate", 0)
    if d != "two_sided" and row.get("p", 1) < alpha and (est > 0) != (d == "positive"):
        return "opposite"
    tp = row.get("tost_p")
    if isinstance(tp, float) and math.isfinite(tp) and tp < alpha and row.get("es_metric") in ("g", "r"):
        return "equivalent"
    return "inconclusive"


def finish_effects(rows: list[dict], plan: Plan) -> pd.DataFrame:
    """Apply multiplicity within the confirmatory and the exploratory family, then verdicts."""
    df = pd.DataFrame(rows, columns=ROW_COLUMNS) if rows else pd.DataFrame(columns=ROW_COLUMNS)
    if df.empty:
        return df
    df["p_adj"] = np.nan
    df["adj_method"] = ""
    for conf in (True, False):
        m = df["confirmatory"] == conf
        if m.any():
            method = plan.multiplicity if conf else "bh"
            df.loc[m, "p_adj"] = adjust(df.loc[m, "p_test"].tolist(), method)
            df.loc[m, "adj_method"] = method
    df["verdict"] = [verdict(r, plan.alpha) for r in df.to_dict("records")]
    return df


# ------------------------------------------------------------------ design diagnostics
def srm_test(counts: dict[str, int], expected: dict[str, float] | None = None) -> dict:
    """Sample-ratio mismatch: do arm sizes match the planned allocation? Flag at p < 0.001."""
    levels = sorted(counts)
    obs = np.array([counts[l] for l in levels], float)
    if len(levels) < 2 or obs.sum() == 0:
        return {"chi2": None, "df": 0, "p": None, "flag": False, "counts": counts}
    if expected:
        w = np.array([expected.get(l, 0.0) for l in levels], float)
        w = w / w.sum() if w.sum() > 0 else np.full(len(levels), 1 / len(levels))
    else:
        w = np.full(len(levels), 1 / len(levels))
    exp = w * obs.sum()
    chi2 = float(((obs - exp) ** 2 / exp).sum())
    p = float(sps.chi2.sf(chi2, len(levels) - 1))
    return {"chi2": round(chi2, 3), "df": len(levels) - 1, "p": p, "flag": p < 0.001, "counts": counts}


def balance_table(df: pd.DataFrame, arm: str, covariates: list[str], control: str) -> pd.DataFrame:
    """Baseline balance: standardised mean difference (numeric) or chi-square p (categorical) per arm vs control."""
    codes = df[arm].map(canon_level)
    rows = []
    for c in covariates:
        s = df[c]
        for lvl in sorted({x for x in codes.unique() if x and x != control}):
            a, b = s[codes == lvl], s[codes == control]
            if pd.api.types.is_numeric_dtype(s):
                a, b = a.dropna().astype(float), b.dropna().astype(float)
                if len(a) < 3 or len(b) < 3:
                    continue
                sd = math.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
                smd = (a.mean() - b.mean()) / sd if sd > 0 else 0.0
                p = float(sps.ttest_ind(a, b, equal_var=False).pvalue)
                rows.append({"covariate": c, "contrast": f"{lvl} vs {control}", "smd": round(smd, 3), "p": p})
            else:
                sub = pd.concat([s[codes == lvl], s[codes == control]]).astype("string")
                g = pd.concat([codes[codes == lvl], codes[codes == control]])
                ct = pd.crosstab(sub.values, g.values)
                if ct.shape[0] < 2 or ct.shape[1] < 2:
                    continue
                rows.append({"covariate": c, "contrast": f"{lvl} vs {control}", "smd": np.nan, "p": float(sps.chi2_contingency(ct)[1])})
    return pd.DataFrame(rows, columns=["covariate", "contrast", "smd", "p"])


def attrition_table(df: pd.DataFrame, arm: str, outcomes: list[str]) -> pd.DataFrame:
    codes = df[arm].map(canon_level)
    rows = []
    for o in outcomes:
        miss = df[o].isna()
        ct = pd.crosstab(codes[codes != ""], miss[codes != ""])
        p = float(sps.chi2_contingency(ct)[1]) if ct.shape == (ct.shape[0], 2) and ct.shape[0] > 1 and (ct.sum(axis=0) > 0).all() else np.nan
        share = miss[codes != ""].groupby(codes[codes != ""]).mean()
        rows.append({"outcome": o, "missing_by_arm": {k: round(float(v), 4) for k, v in share.items()}, "p": p})
    return pd.DataFrame(rows)


def followup_table(effects: pd.DataFrame, alpha: float) -> pd.DataFrame:
    """Sample sizes for a follow-up. Observed effects from a significant first study are inflated on average, so the table
    also shows half the observed effect and, when it excludes zero, the lower confidence bound."""
    rows = []
    for r in effects.to_dict("records"):
        if r["es_metric"] not in ("g", "r"):
            continue
        es, lo, hi = r["es"], r["es_ci_low"], r["es_ci_high"]
        cands = [("observed", es), ("half of observed", es / 2)]
        if np.isfinite(lo) and np.isfinite(hi) and lo * hi > 0:
            cands.append(("nearest confidence bound", lo if abs(lo) < abs(hi) else hi))
        if r.get("sesoi"):
            cands.append(("smallest effect of interest", r["sesoi"] * (1 if es >= 0 else -1)))
        for name, v in cands:
            n = n_per_group(v, alpha, POWER, r["es_metric"])
            cap = 20000 if r["es_metric"] == "g" else 40000
            if n and (n <= cap):
                rows.append({"analysis_id": r["analysis_id"], "basis": name, "effect": round(float(v), 4),
                             "metric": r["es_metric"], "n_per_group": n if r["es_metric"] == "g" else None,
                             "n_total": 2 * n if r["es_metric"] == "g" else n})
    return pd.DataFrame(rows, columns=["analysis_id", "basis", "effect", "metric", "n_per_group", "n_total"])
