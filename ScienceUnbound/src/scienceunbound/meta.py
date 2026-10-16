"""Random-effects meta-analysis across studies in the library.

DerSimonian-Laird heterogeneity with the Hartung-Knapp adjustment (floor at the DL variance), t-based CI, prediction interval,
and an Egger regression when there are at least ten estimates. One estimate per study and construct is used (estimates from one study are not independent). Only effects on the same metric are pooled:
g (group contrasts) or r (pooled on Fisher's z and back-transformed). Interaction estimates are never pooled.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats as sps


def random_effects(y, se) -> dict:
    y, se = np.asarray(y, float), np.asarray(se, float)
    ok = np.isfinite(y) & np.isfinite(se) & (se > 0)
    y, se = y[ok], se[ok]
    k = len(y)
    if k < 2:
        return {"k": k, "pooled": float(y[0]) if k == 1 else float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
                "tau2": float("nan"), "I2": float("nan"), "Q": float("nan"), "Q_p": float("nan"), "pi_low": float("nan"),
                "pi_high": float("nan"), "p": float("nan"), "se": float("nan")}
    w = 1 / se**2
    fixed = float((w * y).sum() / w.sum())
    Q = float((w * (y - fixed) ** 2).sum())
    C = float(w.sum() - (w**2).sum() / w.sum())
    tau2 = max(0.0, (Q - (k - 1)) / C) if C > 0 else 0.0
    ws = 1 / (se**2 + tau2)
    mu = float((ws * y).sum() / ws.sum())
    se_dl = math.sqrt(1 / ws.sum())
    q = float((ws * (y - mu) ** 2).sum() / (k - 1))
    se_hk = se_dl * math.sqrt(max(1.0, q))
    tc = sps.t.ppf(0.975, k - 1)
    pi_low = pi_high = float("nan")
    if k >= 3:
        tp = sps.t.ppf(0.975, k - 2)
        half = tp * math.sqrt(tau2 + se_hk**2)
        pi_low, pi_high = mu - half, mu + half
    return {"k": k, "pooled": mu, "se": se_hk, "ci_low": mu - tc * se_hk, "ci_high": mu + tc * se_hk, "tau2": tau2,
            "I2": max(0.0, (Q - (k - 1)) / Q) if Q > 0 else 0.0, "Q": Q, "Q_p": float(sps.chi2.sf(Q, k - 1)),
            "pi_low": pi_low, "pi_high": pi_high, "p": float(2 * sps.t.sf(abs(mu / se_hk), k - 1))}


def egger(y, se) -> dict | None:
    y, se = np.asarray(y, float), np.asarray(se, float)
    if len(y) < 10:
        return None
    z, prec = y / se, 1 / se
    X = np.column_stack([np.ones_like(prec), prec])
    beta, *_ = np.linalg.lstsq(X, z, rcond=None)
    resid = z - X @ beta
    dof = len(y) - 2
    s2 = (resid**2).sum() / dof
    cov = s2 * np.linalg.inv(X.T @ X)
    t = beta[0] / math.sqrt(cov[0, 0])
    return {"intercept": float(beta[0]), "p": float(2 * sps.t.sf(abs(t), dof))}


def pool_frame(effects: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Rows eligible for pooling: confirmatory, same metric, finite es and se. r is moved to Fisher's z."""
    d = effects[(effects["es_metric"] == metric)].copy()
    if "confirmatory" in d.columns:
        d = d[d["confirmatory"].astype(str).str.lower().isin(["true", "1"])]
    if metric == "r":
        d["yi"] = np.arctanh(d["es"].clip(-0.999999, 0.999999))
    else:
        d["yi"] = d["es"]
    d["sei"] = d["es_se"]
    return d.dropna(subset=["yi", "sei"])


def meta_by_construct(effects: pd.DataFrame, min_k: int = 2) -> pd.DataFrame:
    """effects: concatenated results/effects.csv of many studies with a `study` column. One pooled row per construct and metric."""
    rows = []
    for metric in ("g", "r"):
        d = pool_frame(effects, metric)
        d = d[d["construct"].astype(str).str.strip() != ""]
        for construct, g_all in d.groupby("construct"):
            # Estimates from one study share a control group and respondents, so they are not independent.
            # Use one per study: the first in plan order, a choice that cannot depend on the results.
            g = g_all.groupby("study", sort=False).head(1)
            if len(g) < min_k:
                continue
            res = random_effects(g["yi"], g["sei"])
            back = (lambda v: math.tanh(v)) if metric == "r" else (lambda v: v)
            rows.append({"construct": construct, "metric": metric, "k": res["k"], "studies": g["study"].nunique(), "dependent_excluded": int(len(g_all) - len(g)),
                         "pooled": back(res["pooled"]), "ci_low": back(res["ci_low"]), "ci_high": back(res["ci_high"]),
                         "tau2": res["tau2"], "I2": res["I2"], "Q_p": res["Q_p"], "p": res["p"],
                         "pi_low": back(res["pi_low"]) if np.isfinite(res["pi_low"]) else np.nan,
                         "pi_high": back(res["pi_high"]) if np.isfinite(res["pi_high"]) else np.nan})
    return pd.DataFrame(rows)
