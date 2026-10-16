"""Deterministic report writer. Every number is rendered from a results table; no model types a number.

Optional narrative (summary, limitations) may come from an LLM, but only through placeholders such as {{H1:info.es}}
that are filled from the tables here, and verify.py checks the finished text independently.
"""
from __future__ import annotations

import math
import platform
import re
from typing import Any

import pandas as pd

from . import __version__
from .analyze import AnalysisResult
from .credits import LICENSE_CONTENT, NOT_AFFILIATED, ONE_LINE, ORIGINATOR, ORIGINATOR_PROJECT, ORIGINATOR_REPO, SUGGESTED_BY, TOOL_NAME
from .schema import Plan

MINUS = "−"
VERIF_START, VERIF_END = "<!-- su:verification:start -->", "<!-- su:verification:end -->"
VERIF_SLOT = f"{VERIF_START}\n{{VERIFICATION}}\n{VERIF_END}"
TABLE_HEADERS = ["Analysis", "Contrast", "N", "Estimate", "Effect size [{ci}% CI]", "Test", "p", "p (adj.)", "Verdict", "Status"]
METRIC_NAME = {"g": "g", "r": "r", "g_int": "g (interaction)"}
VERDICT_TEXT = {"supported": "supported", "opposite": "opposite direction", "equivalent": "equivalent to zero",
                "inconclusive": "inconclusive"}
TAG_TEXT = {"registered": "registered", "deviation": "deviation", "unregistered": "added after lock",
            "exploratory": "exploratory", "unlocked": "plan not locked"}


def fnum(x: Any, d: int = 2) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    s = f"{abs(float(x)):.{d}f}"
    neg = float(x) < 0 and float(s) != 0
    return (MINUS if neg else "") + s


def fp(p: Any) -> str:
    """'.030' style; values below .001 are '< .001'."""
    if p is None or (isinstance(p, float) and not math.isfinite(p)):
        return "n/a"
    p = float(p)
    return "< .001" if p < 0.001 else (f"{p:.3f}" if p >= 1 else f"{p:.3f}".lstrip("0"))


def ptxt(p: Any, prefix: str = "p") -> str:
    s = fp(p)
    return f"{prefix} {s}" if s.startswith("<") else (f"{prefix} = {s}" if s != "n/a" else f"{prefix} n/a")


def A(text: Any) -> str:
    """Mark author-written text: shown as is, never counted as a pipeline claim."""
    s = str(text)
    return f"<!-- su:author -->{s}<!-- su:/author -->" if s else s


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "/") for c in r) + " |")
    return "\n".join(out)


def test_kind(r: dict) -> str:
    return {"positive": "one-sided (+)", "negative": "one-sided (\u2212)"}.get(r["direction"], "two-sided")


def effect_cell(r: dict) -> str:
    return f"{fnum(r['es'])} [{fnum(r['es_ci_low'])}, {fnum(r['es_ci_high'])}]"


def _ci_pct(plan: Plan) -> str:
    return f"{round(100 * (1 - plan.alpha))}"


def _fill(text: str, eff: pd.DataFrame) -> str:
    """Replace {{ID.col}} placeholders from the results table; unknown placeholders raise."""
    idx = eff.set_index("analysis_id")

    def rep(m):
        aid, col = m.group(1), m.group(2)
        if aid not in idx.index or col not in idx.columns:
            raise ValueError(f"unknown placeholder {{{{{aid}.{col}}}}}")
        v = idx.loc[aid, col]
        if col in ("p", "p_adj", "tost_p"):
            return fp(v)
        if col in ("n", "n_level", "n_reference"):
            return str(int(v))
        return fnum(v)

    return re.sub(r"\{\{\s*([A-Za-z0-9_:\-.x]+?)\.([a-z_]+)\s*\}\}", rep, text)


def result_line(r: dict, plan: Plan) -> str:
    metric = METRIC_NAME[r["es_metric"]]
    head = (f"**{r['analysis_id']}** — {A(r['contrast'])} on {A(r['outcome'])}: {metric} = {effect_cell(r)}, "
            f"{ptxt(r['p_test'])} ({test_kind(r).split(' ')[0]}), adjusted {ptxt(r['p_adj'])}, N = {int(r['n'])}.")
    tail = f" Verdict: {VERDICT_TEXT[r['verdict']]}."
    if r["verdict"] == "equivalent":
        tail += f" Equivalence to zero within ±{fnum(r['sesoi'])} SD was shown by two one-sided tests ({ptxt(r['tost_p'])}; these use a 90% interval)."
    elif r["verdict"] in ("inconclusive",):
        tail += f" The design could detect effects of {fnum(abs(r['mde_es']))} or larger with 80% power"
        tail += (f"; equivalence within ±{fnum(r['sesoi'])} SD was not shown ({ptxt(r['tost_p'], 'equivalence test p')})." if r["sesoi"] and isinstance(r.get("tost_p"), float) and math.isfinite(r["tost_p"]) else ".")
    if r.get("note"):
        tail += f" Note: {r['note']}."
    return head + tail


def results_table(eff: pd.DataFrame, plan: Plan) -> str:
    hdr = [h.format(ci=_ci_pct(plan)) for h in TABLE_HEADERS]
    rows = [[r["analysis_id"], A(r["contrast"]), int(r["n"]), fnum(r["estimate"]), effect_cell(r), test_kind(r), fp(r["p_test"]), fp(r["p_adj"]),
             VERDICT_TEXT[r["verdict"]], TAG_TEXT.get(r["tag"], r["tag"])] for r in eff.to_dict("records")]
    return md_table(hdr, rows)


def auto_summary(res: AnalysisResult) -> str:
    plan, eff = res.plan, res.effects
    n = len(res.data)
    conf = eff[eff["confirmatory"]]
    design = ("randomized experiment" if plan.design == "randomized" else "observational study")
    s = [f"This {design} analyses {n:,} respondents after exclusions."]
    if conf.empty:
        return s[0]
    counts = conf["verdict"].value_counts().to_dict()
    bits = []
    for v, label in (("supported", "supported"), ("equivalent", "equivalent to zero within the smallest effect of interest"),
                     ("inconclusive", "inconclusive"), ("opposite", "in the opposite direction")):
        if counts.get(v):
            bits.append(f"{counts[v]} {'was' if counts[v] == 1 else 'were'} {label}")
    s.append(f"Of {len(conf)} confirmatory estimates, " + ", ".join(bits) + ".")
    causal = plan.design == "randomized"
    for r in conf[conf["verdict"] == "supported"].to_dict("records"):
        s.append(f"{r['analysis_id']} ({A(r['label'])}): {METRIC_NAME[r['es_metric']]} = {effect_cell(r)}.")
    if not causal:
        s.append("Estimates describe associations; the design does not identify causal effects.")
    return " ".join(s)


def _limitations(res: AnalysisResult) -> list[str]:
    plan, eff = res.plan, res.effects
    L = []
    if plan.design == "randomized":
        L.append("Treatment was randomised according to the plan; the sample-ratio and balance checks below test that assumption, not prove it.")
    else:
        L.append("The design is observational. Estimates are conditional associations and are not causal effects.")
    L.append("Outcomes are analysed with linear models (heteroskedasticity-robust errors unless stated). Binary outcomes are linear probability models.")
    L.append("Rows with a missing outcome or covariate are dropped listwise; the table shows how many were dropped per estimate.")
    L.append(f"Multiplicity: {({'holm': 'Holm', 'bh': 'Benjamini-Hochberg', 'none': 'no'})[plan.multiplicity]} adjustment is applied within the confirmatory family; exploratory estimates form their own family with Benjamini-Hochberg adjustment.")
    low = eff[eff["confirmatory"] & (eff["verdict"] == "inconclusive")]
    if len(low):
        L.append(f"{len(low)} confirmatory estimates are inconclusive: the study could not rule effects of the sizes shown in 'could detect' out, and absence of significance is not evidence of absence.")
    if any(h.weights for h in plan.hypotheses):
        L.append("Survey weights enter as analytic weights in weighted least squares with robust errors. The sampling design (strata, clusters) is not modelled.")
    else:
        L.append("No survey weights were used; estimates describe the sample, not a weighted population.")
    L.append("This report was produced by an automated pipeline. No human review is recorded unless the provenance line says so.")
    return L


def build_report(res: AnalysisResult, *, lock: dict | None, priv: dict | None, include_data: bool, repo_url: str,
                 generated_on: str, figures: dict[str, bool], narrative: dict | None = None, env: dict | None = None) -> str:
    plan, eff = res.plan, res.effects
    priv = priv or {}
    env = env or {}
    L: list[str] = []
    L.append(f"# {plan.title}")
    L.append("")
    L.append(f"**Provenance:** automated analysis with {TOOL_NAME} {__version__}; no human review recorded. "
             f"**Plan:** {res.timing['text']} ")
    L.append("")
    L.append(VERIF_SLOT)
    L.append("")
    L.append("Authors: " + A(", ".join(plan.authors) or "not stated"))
    L.append("")
    L.append("## Summary")
    L.append("")
    summary = (narrative or {}).get("summary")
    L.append(_fill(summary, eff) if summary else auto_summary(res))
    L.append("")
    if plan.summary:
        L.append(A(plan.summary))
        L.append("")
    L.append("## Design and sample")
    L.append("")
    L.append(md_table(["Step", "Removed", "Remaining"], [[f["step"], f["removed"], f["remaining"]] for f in res.flow]))
    L.append("")
    if res.srm.get("counts"):
        L.append(md_table(["Arm", "N"], [[A(plan.arm_labels.get(k) or k), v] for k, v in sorted(res.srm["counts"].items())]))
        L.append("")
    for name, i in res.outcome_info.items():
        extra = f", Cronbach's alpha = {i['alpha']:.2f}" if i.get("alpha") is not None else ""
        L.append(f"- Outcome `{name}`: {i['kind']} of {i['n_items']} item(s), valid N = {i['n_valid']}{extra}.")
    L.append("")
    L.append("## Plan and registration status")
    L.append("")
    L.append(res.timing["text"])
    if plan.registration_url:
        L.append(f"\nExternal registration listed by the authors (not verified by {TOOL_NAME}): {plan.registration_url}")
    L.append("")
    L.append(md_table(["Hypothesis", "Status", "Differences from the locked plan", "Reason given"],
                      [[t["id"], TAG_TEXT.get(t["tag"], t["tag"]), ("`" + "`, `".join(t["differences"]) + "`") if t["differences"] else "none", A(t["reason"] or "")] for t in res.tags]))
    if res.registered_not_run:
        L.append("\nRegistered but not run: " + ", ".join(res.registered_not_run) + ".")
    L.append("")
    conf = eff[eff["confirmatory"]]
    L.append("## Confirmatory results")
    L.append("")
    if conf.empty:
        L.append("No confirmatory estimates.")
    else:
        L.append(results_table(conf, plan))
        L.append("")
        for r in conf.to_dict("records"):
            L.append("- " + result_line(r, plan))
        if figures.get("forest"):
            L.append("\n![Forest plot of all estimates](figures/forest.png)")
    L.append("")
    expl = eff[~eff["confirmatory"]]
    if len(expl):
        L.append("## Exploratory results (EXPLORATORY — not pre-registered)")
        L.append("")
        L.append(results_table(expl, plan))
        L.append("")
        for r in expl.to_dict("records"):
            L.append("- " + result_line(r, plan))
        L.append("")
    if len(res.spec_summary):
        L.append("## Robustness: specification curves")
        L.append("")
        L.append("Each estimate was recomputed under every combination of covariate set, error type and outlier handling listed in the "
                 "specification table. The table shows how many variants agree with the main estimate.")
        L.append("")
        L.append(md_table(["Analysis", "Variants", "Same sign", "p below alpha", "Smallest effect size", "Median", "Largest"],
                          [[r["analysis_id"], r["n_specs"], f"{r['share_same_sign']:.2f}", f"{r['share_p_below_alpha']:.2f}",
                            fnum(r["es_min"]), fnum(r["es_median"]), fnum(r["es_max"])] for r in res.spec_summary.to_dict("records")]))
        if figures.get("spec"):
            L.append("\n![Specification curves](figures/spec_curves.png)")
        L.append("")
    L.append("## Design checks")
    L.append("")
    if res.srm.get("p") is not None:
        L.append(f"- Sample-ratio check: chi-square = {res.srm['chi2']:.2f}, {ptxt(res.srm['p'])}" + (" (mismatch flagged)." if res.srm["flag"] else "."))
    if len(res.balance):
        nb = int((res.balance["p"] < 0.05).sum())
        L.append(f"- Baseline balance: {nb} of {len(res.balance)} covariate comparisons have p below .05 (about 5% are expected by chance).")
    no_missing = bool(len(res.attrition)) and all(v == 0 for m in res.attrition["missing_by_arm"] for v in m.values())
    if no_missing:
        L.append("- No outcome values are missing in any arm.")
    for r in ([] if no_missing else res.attrition.to_dict("records")):
        L.append(f"- Missing outcomes, {A(r['outcome'])}: " + ", ".join(f"{k} {v * 100:.1f}%" for k, v in sorted(r["missing_by_arm"].items())) +
                 (f" ({ptxt(r['p'])})." if isinstance(r["p"], float) and math.isfinite(r["p"]) else "."))
    if res.warnings:
        L.append("")
        L.append("Warnings raised by the pipeline:")
        for w in res.warnings:
            L.append(f"- {w}")
    L.append("")
    if len(res.followups):
        L.append("## What a follow-up would need")
        L.append("")
        L.append("Sample sizes for 80% power at the plan's alpha (two groups, equal allocation, normal approximation; for correlations, total N). "
                 "A first study that happened to be significant overstates the true effect on average, so smaller effects are shown too. "
                 "Effects that would need an impractically large sample are omitted.")
        L.append("")
        L.append(md_table(["Analysis", "Effect assumed", "Value", "N per group", "N total"],
                          [[r["analysis_id"], r["basis"], fnum(r["effect"]), "" if pd.isna(r["n_per_group"]) else int(r["n_per_group"]),
                            int(r["n_total"])] for r in res.followups.to_dict("records")]))
        L.append("")
    L.append("## Limitations")
    L.append("")
    for item in ((narrative or {}).get("limitations") or _limitations(res)):
        L.append(f"- {_fill(item, eff)}")
    L.append("")
    L.append("## Privacy and data")
    L.append("")
    dropped = priv.get("dropped") or []
    L.append(f"Before analysis, {len(dropped)} column(s) were removed after a scan of every cell: " + (", ".join(f"`{c}`" for c in dropped) or "none") + ".")
    for col, why in (priv.get("kept") or {}).items():
        L.append(f"Kept although flagged: `{col}`. Reason given by the authors: {A(why)}")
    if priv.get("k_actions") is not None:
        k = priv.get("k_stats") or {}
        L.append(f"Re-identification check on {', '.join('`' + c + '`' for c in (k.get('quasi') or [])) or 'no columns'}: "
                 f"every combination is shared by at least {k.get('min_k') if k.get('min_k') is not None else 'n/a'} respondents (target {k.get('k_target', 'n/a')}).")
        if k.get("min_k") is not None and k.get("k_target") and k["min_k"] < k["k_target"]:
            L.append(f"**Warning:** {k['rows_below_k']} respondents are in combinations smaller than the target. Respondent-level data should not be published.")
        for a in priv["k_actions"]:
            L.append(f"- Generalised: {a}")
    L.append("")
    L.append("Respondent-level data " + ("are included in this package (`data/analysis_input.csv`)." if include_data else
             f"are not included. The SHA-256 of the de-identified analysis table, serialised as CSV, is `{res.data_sha256}`, so a data holder can confirm identical input."))
    L.append("")
    L.append("## Provenance and reproducibility")
    L.append("")
    L.append(f"- Generated {generated_on} by {TOOL_NAME} {__version__}.")
    L.append(f"- Plan SHA-256 `{res.plan_sha256}`; random seed {plan.seed}.")
    L.append("- Environment: " + ", ".join(f"{k} {v}" for k, v in sorted({**env, 'python': platform.python_version()}.items())) + ".")
    L.append("- `scripts/reproduce.py` re-runs the analysis and compares every number with `results/effects.csv`.")
    L.append("")
    L.append("## How to cite")
    L.append("")
    L.append(A(f"{', '.join(plan.authors) or 'Authors'}. {plan.title}.") + f" {TOOL_NAME} study report, {generated_on}. {repo_url or ''}".rstrip())
    L.append("")
    L.append(f"Content licence: {LICENSE_CONTENT}.")
    L.append("")
    L.append("## Credits")
    L.append("")
    L.append(ONE_LINE)
    L.append("")
    L.append(NOT_AFFILIATED)
    L.append("")
    return "\n".join(L)
