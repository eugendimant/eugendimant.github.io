"""Run a plan on a data frame: exclusions, outcomes, estimates, multiplicity, tags, diagnostics, robustness."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import registration as REG
from . import stats as S
from .ingest import frame_sha256
from .schema import Hypothesis, Plan, canon_level, plan_hash, validate_plan


@dataclass
class AnalysisResult:
    plan: Plan
    data: pd.DataFrame                        # analysis sample with constructed outcomes
    flow: list[dict]
    outcome_info: dict
    effects: pd.DataFrame
    spec: pd.DataFrame
    spec_summary: pd.DataFrame
    balance: pd.DataFrame
    attrition: pd.DataFrame
    srm: dict
    followups: pd.DataFrame
    tags: list[dict]
    registered_not_run: list[str]
    timing: dict
    warnings: list[str] = field(default_factory=list)
    data_sha256: str = ""
    plan_sha256: str = ""


def _winsorise(y: pd.Series, q: float = 0.01) -> pd.Series:
    lo, hi = y.quantile(q), y.quantile(1 - q)
    return y.clip(lo, hi)


def spec_curve(df: pd.DataFrame, plan: Plan, effects: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Re-estimate each confirmatory contrast under defensible alternatives: covariate sets, error types, outlier handling.

    Deterministic and exhaustive over a small grid, so a reader can see how much a conclusion depends on analyst choices.
    """
    all_covs = sorted({c for h in plan.hypotheses for c in h.covariates})
    rows = []
    for h in plan.hypotheses:
        if h.moderator:
            continue
        cov_sets = {"no covariates": [], "planned covariates": list(h.covariates)}
        if all_covs and set(all_covs) != set(h.covariates):
            cov_sets["all declared covariates"] = [c for c in all_covs if c not in (h.predictor or plan.arm_column)]
        ses = ["HC2", "HC3", "classical"] + (["cluster"] if h.se == "cluster" else [])
        outl = {"raw outcome": False, "winsorised 1%/99%": True}
        seen = set()
        for (cn, covs), se, (on, w) in itertools.product(cov_sets.items(), ses, outl.items()):
            key = (tuple(covs), se, w)
            if key in seen:
                continue
            seen.add(key)
            d = df
            if w:
                d = df.copy()
                d[h.outcome] = _winsorise(d[h.outcome].astype(float))
            h2 = Hypothesis(**{**h.__dict__, "covariates": covs, "se": se, "sesoi": None, "levels": list(h.levels)})
            for r in S.estimate_hypothesis(d, plan, h2):
                rows.append({"analysis_id": r["analysis_id"], "covariates": cn, "errors": se, "outcome_handling": on,
                             "estimate": r["estimate"], "p": r["p"], "es": r["es"], "es_metric": r["es_metric"],
                             "ci_low": r["es_ci_low"], "ci_high": r["es_ci_high"]})
    spec = pd.DataFrame(rows, columns=["analysis_id", "covariates", "errors", "outcome_handling", "estimate", "p", "es",
                                        "es_metric", "ci_low", "ci_high"])
    summ = []
    prim = effects.set_index("analysis_id")
    for aid, g in spec.groupby("analysis_id"):
        if aid not in prim.index:
            continue
        est0 = prim.loc[aid, "estimate"]
        summ.append({"analysis_id": aid, "n_specs": int(len(g)),
                     "share_same_sign": round(float((np.sign(g["estimate"]) == np.sign(est0)).mean()), 3),
                     "share_p_below_alpha": round(float((g["p"] < plan.alpha).mean()), 3),
                     "es_min": round(float(g["es"].min()), 4), "es_median": round(float(g["es"].median()), 4),
                     "es_max": round(float(g["es"].max()), 4)})
    return spec, pd.DataFrame(summ, columns=["analysis_id", "n_specs", "share_same_sign", "share_p_below_alpha",
                                              "es_min", "es_median", "es_max"])


def run_analysis(df_in: pd.DataFrame, plan: Plan, lock: dict | None = None, with_spec: bool = True) -> AnalysisResult:
    problems = validate_plan(plan, list(df_in.columns))
    if problems:
        raise ValueError("The plan cannot run:\n- " + "\n- ".join(problems))
    warns: list[str] = []
    df, flow = S.apply_exclusions(df_in, plan.exclusions)
    df, info, w2 = S.construct_outcomes(df, plan.outcomes)
    warns += w2
    if plan.design == "randomized":
        codes = df[plan.arm_column].map(canon_level)
        known = {l for l in codes.unique() if l}
        if plan.control_level not in known:
            raise ValueError(f"control level '{plan.control_level}' does not occur in '{plan.arm_column}' (found: {sorted(known)})")
    rows: list[dict] = []
    for h in plan.hypotheses:
        rr = S.estimate_hypothesis(df, plan, h)
        if not rr:
            warns.append(f"{h.id}: no estimable contrast (too few observations in a group)")
        rows += rr
    effects = S.finish_effects(rows, plan)
    tags, not_run = REG.tag_hypotheses(plan, lock)
    tag_by = {t["id"]: t["tag"] for t in tags}
    if not effects.empty:
        effects["tag"] = effects["hypothesis"].map(tag_by)
    for t in tags:
        if t["tag"] == "deviation" and not t["reason"]:
            warns.append(f"{t['id']} differs from the locked plan ({', '.join(t['differences'][:3])}) and no reason is stated")
    for hid in not_run:
        warns.append(f"{hid} is in the locked plan but was not run")
    srm = {"chi2": None, "df": 0, "p": None, "flag": False, "counts": {}}
    balance = pd.DataFrame(columns=["covariate", "contrast", "smd", "p"])
    attr = pd.DataFrame(columns=["outcome", "missing_by_arm", "p"])
    if plan.design == "randomized":
        counts = df[plan.arm_column].map(canon_level)
        counts = counts[counts != ""].value_counts().to_dict()
        srm = S.srm_test({str(k): int(v) for k, v in counts.items()}, plan.expected_allocation or None)
        if srm["flag"]:
            warns.append(f"sample-ratio mismatch (chi-square p = {srm['p']:.2g}): arm sizes differ from the planned allocation")
        covs = sorted({c for h in plan.hypotheses for c in h.covariates if c != plan.arm_column})
        if covs:
            balance = S.balance_table(df, plan.arm_column, covs, plan.control_level)
        attr = S.attrition_table(df, plan.arm_column, [o.name for o in plan.outcomes])
        if len(attr) and (attr["p"] < 0.01).any():
            bad = attr.loc[attr["p"] < 0.01, "outcome"].tolist()
            warns.append("differential missingness across arms for: " + ", ".join(bad))
    if with_spec and not effects.empty:
        spec, spec_sum = spec_curve(df, plan, effects)
    else:
        spec = pd.DataFrame(); spec_sum = pd.DataFrame()
    fu = S.followup_table(effects, plan.alpha) if not effects.empty else pd.DataFrame()
    return AnalysisResult(plan=plan, data=df, flow=flow, outcome_info=info, effects=effects, spec=spec,
                          spec_summary=spec_sum, balance=balance, attrition=attr, srm=srm, followups=fu, tags=tags,
                          registered_not_run=not_run, timing=REG.timing_status(plan, lock), warnings=warns,
                          data_sha256=frame_sha256(df_in), plan_sha256=plan_hash(plan))
