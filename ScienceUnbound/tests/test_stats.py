import math

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from scipy import stats as sps
from statsmodels.stats.weightstats import ttost_ind

from scienceunbound import stats as S
from scienceunbound.schema import Exclusion, Hypothesis, Outcome, Plan


def two_arm(n=120, b=0.3, seed=0, sd=1.0):
    rng = np.random.default_rng(seed)
    arm = np.repeat(["c", "t"], n)
    y = rng.normal(0, sd, 2 * n) + np.where(arm == "t", b, 0)
    x = rng.normal(size=2 * n)
    return pd.DataFrame({"arm": arm, "y": y, "x": x})


def plan_for(h: Hypothesis) -> Plan:
    return Plan(title="t", slug="tt", design="randomized", arm_column="arm", control_level="c",
                outcomes=[Outcome(name="out", items=["y"])], hypotheses=[h])


def one(df, **kw):
    h = Hypothesis(id="H1", label="x", outcome="out", **kw)
    d, _, _ = S.construct_outcomes(df, [Outcome(name="out", items=["y"])])
    return S.estimate_hypothesis(d, plan_for(h), h)[0]


def test_classical_matches_scipy_exactly():
    df = two_arm()
    r = one(df, se="classical")
    a, b = df.loc[df.arm == "t", "y"], df.loc[df.arm == "c", "y"]
    t = sps.ttest_ind(a, b, equal_var=True)
    assert math.isclose(r["estimate"], a.mean() - b.mean(), rel_tol=1e-12)
    assert math.isclose(r["p"], t.pvalue, rel_tol=1e-9)
    sp = math.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
    J = 1 - 3 / (4 * (len(a) + len(b) - 2) - 1)
    assert math.isclose(r["es"], (a.mean() - b.mean()) / sp * J, rel_tol=1e-12)
    assert math.isclose(r["se"], sp * math.sqrt(1 / len(a) + 1 / len(b)), rel_tol=1e-9)


def test_hc2_matches_a_hand_written_sandwich():
    df = two_arm(seed=3)
    df["y"] = df["y"] * np.where(df.arm == "t", 2.0, 0.7)          # heteroskedastic on purpose
    r = one(df, se="HC2", covariates=["x"])
    X = np.column_stack([np.ones(len(df)), (df.arm == "t").astype(float), df.x])
    y = df.y.to_numpy()
    XtXi = np.linalg.inv(X.T @ X)
    e = y - X @ (XtXi @ X.T @ y)
    h = np.einsum("ij,jk,ik->i", X, XtXi, X)
    meat = (X * (e**2 / (1 - h))[:, None]).T @ X
    V = XtXi @ meat @ XtXi
    assert math.isclose(r["se"], math.sqrt(V[1, 1]), rel_tol=1e-9)


def test_tost_matches_statsmodels():
    df = two_arm(n=200, b=0.05, seed=5)
    r = one(df, se="classical", sesoi=0.3)
    a, b = df.loc[df.arm == "t", "y"].to_numpy(), df.loc[df.arm == "c", "y"].to_numpy()
    sp = math.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
    J = 1 - 3 / (4 * (len(a) + len(b) - 2) - 1)
    delta = 0.3 * sp / J
    p_sm = ttost_ind(a, b, -delta, delta, usevar="pooled")[0]
    assert math.isclose(r["tost_p"], p_sm, rel_tol=1e-6)


def test_holm_and_bh_known_values():
    p = np.array([0.01, 0.04, 0.03, 0.005])
    assert np.allclose(S.holm(p), [0.03, 0.06, 0.06, 0.02])
    bh = S.bh(p)
    assert np.allclose(bh, [0.02, 0.04, 0.04, 0.02])
    assert (S.holm(p) >= p).all()


def test_sample_size_matches_the_textbook():
    assert S.n_per_group(0.5) == 63
    assert S.n_per_group(0.2) == 393
    assert S.n_per_group(0) is None


def test_cronbach_alpha_matches_the_definition():
    rng = np.random.default_rng(2)
    base = rng.normal(size=300)
    M = pd.DataFrame({f"i{k}": base + rng.normal(size=300) for k in range(4)})
    k = 4
    expected = k / (k - 1) * (1 - M.var(ddof=1).sum() / M.sum(axis=1).var(ddof=1))
    assert math.isclose(S.cronbach_alpha(M), expected, rel_tol=1e-12)


def test_continuous_predictor_r_equals_pearson_without_covariates():
    rng = np.random.default_rng(4)
    x = rng.normal(size=250)
    df = pd.DataFrame({"arm": "c", "x": x, "y": 0.4 * x + rng.normal(size=250)})
    h = Hypothesis(id="H1", label="x", outcome="out", predictor="x", predictor_type="continuous", se="classical")
    d, _, _ = S.construct_outcomes(df, [Outcome(name="out", items=["y"])])
    p = Plan(title="t", slug="tt", design="observational", outcomes=[Outcome(name="out", items=["y"])], hypotheses=[h])
    r = S.estimate_hypothesis(d, p, h)[0]
    assert math.isclose(r["es"], sps.pearsonr(df.x, df.y)[0], rel_tol=1e-9)
    assert r["es_metric"] == "r" and r["es_ci_low"] < r["es"] < r["es_ci_high"]


def test_ci_coverage_and_type_one_error_in_simulation():
    """Planted truth, many replications: a 95% CI must cover the truth about 95% of the time; a true null must be rejected about 5%."""
    reps, n = 600, 80
    cover = rej = 0
    for i in range(reps):
        df = two_arm(n=n, b=0.3, seed=1000 + i)
        r = one(df, se="HC2")
        cover += r["ci_low"] <= 0.3 <= r["ci_high"]
        null = one(two_arm(n=n, b=0.0, seed=5000 + i), se="HC2")
        rej += null["p"] < 0.05
    assert 0.925 <= cover / reps <= 0.975, cover / reps
    assert 0.03 <= rej / reps <= 0.075, rej / reps


def test_the_effect_size_ci_covers_the_true_g_in_simulation():
    reps, n, hits = 400, 100, 0
    true_g = 0.4
    for i in range(reps):
        r = one(two_arm(n=n, b=true_g, seed=9000 + i, sd=1.0), se="HC2")
        hits += r["es_ci_low"] <= true_g <= r["es_ci_high"]
    assert 0.92 <= hits / reps <= 0.98, hits / reps


def test_moderation_recovers_a_planted_interaction():
    rng = np.random.default_rng(8)
    n = 800
    arm = rng.choice(["c", "t"], n)
    m = rng.choice(["a", "b"], n)
    y = rng.normal(size=n) + np.where((arm == "t") & (m == "b"), 0.8, 0.0)
    df = pd.DataFrame({"arm": arm, "y": y, "m": m})
    h = Hypothesis(id="H1", label="x", outcome="out", moderator="m")
    d, _, _ = S.construct_outcomes(df, [Outcome(name="out", items=["y"])])
    rows = S.estimate_hypothesis(d, plan_for(h), h)
    assert len(rows) == 1 and rows[0]["es_metric"] == "g_int"
    assert rows[0]["ci_low"] < 0.8 < rows[0]["ci_high"]


def test_cluster_errors_are_wider_than_naive_when_clusters_matter():
    rng = np.random.default_rng(6)
    g = np.repeat(np.arange(60), 10)
    shock = rng.normal(size=60)[g]
    arm = np.where(np.arange(60)[g] % 2 == 0, "t", "c")
    df = pd.DataFrame({"arm": arm, "y": shock + rng.normal(size=600) * 0.5, "g": g})
    naive = one(df, se="HC2")
    clus = one(df, se="cluster", cluster="g")
    assert clus["se"] > 1.5 * naive["se"]


def test_verdicts_follow_the_evidence():
    big_null = one(two_arm(n=1500, b=0.0, seed=11), sesoi=0.2)
    assert S.verdict({**big_null, "p_adj": big_null["p"]}, 0.05) == "equivalent"
    small_null = one(two_arm(n=25, b=0.0, seed=11), sesoi=0.2)
    assert S.verdict({**small_null, "p_adj": small_null["p"]}, 0.05) == "inconclusive"
    eff = one(two_arm(n=300, b=0.6, seed=12), direction="positive")
    assert S.verdict({**eff, "p_adj": eff["p_test"]}, 0.05) == "supported"
    wrong = one(two_arm(n=300, b=-0.6, seed=12), direction="positive")
    assert S.verdict({**wrong, "p_adj": wrong["p_test"]}, 0.05) == "opposite"


def test_adjusted_p_never_below_unadjusted_and_families_are_separate(demo_result):
    e = demo_result.effects
    assert (e["p_adj"] + 1e-12 >= e["p_test"]).all()
    assert set(e.loc[e.confirmatory, "adj_method"]) == {"holm"} and set(e.loc[~e.confirmatory, "adj_method"]) == {"bh"}


def test_exclusions_are_structured_and_never_evaluated():
    df = pd.DataFrame({"a": [1, 2, 3, 4, None], "s": ["x", "y", "__import__('os').system('echo hacked')", "x", "y"]})
    out, flow = S.apply_exclusions(df, [Exclusion("a", ">", 3), Exclusion("s", "==", "__import__('os').system('echo hacked')"),
                                         Exclusion("a", "isna")])
    assert list(out["a"]) == [1, 2]
    assert [f["removed"] for f in flow] == [0, 1, 1, 1]


def test_srm_flags_a_broken_randomizer_but_not_a_fair_one():
    assert S.srm_test({"a": 500, "b": 500})["flag"] is False
    assert S.srm_test({"a": 600, "b": 400})["flag"] is True
    assert S.srm_test({"a": 700, "b": 300}, {"a": 0.7, "b": 0.3})["flag"] is False


def test_collinear_covariates_do_not_break_the_fit():
    df = two_arm()
    df["x2"] = df["x"] * 2
    df["const_cov"] = 1.0
    r = one(df, covariates=["x", "x2", "const_cov"])
    assert math.isfinite(r["se"]) and "dropped" in r["note"]


# ---- survey weights
def test_weighted_estimate_matches_statsmodels_wls_and_unit_weights_match_unweighted():
    rng = np.random.default_rng(21)
    df = two_arm(n=150, b=0.4, seed=21)
    df["w"] = rng.uniform(0.3, 3.0, len(df))
    r = one(df, se="HC2", weights="w", covariates=["x"])
    X = sm.add_constant(pd.DataFrame({"treat": (df.arm == "t").astype(float), "x": df.x}))
    ref = sm.WLS(df.y, X, weights=df.w).fit(cov_type="HC2")
    assert math.isclose(r["estimate"], ref.params["treat"], rel_tol=1e-9) and math.isclose(r["se"], ref.bse["treat"], rel_tol=1e-9)
    df["one"] = 1.0
    a, b = one(df, se="HC2", weights="one", covariates=["x"]), one(df, se="HC2", covariates=["x"])
    assert math.isclose(a["es"], b["es"], rel_tol=1e-9) and math.isclose(a["se"], b["se"], rel_tol=1e-9)
    assert "weighted" in r["note"]


def test_nonpositive_or_missing_weights_drop_those_rows_and_are_counted():
    df = two_arm(n=100, b=0.2, seed=5)
    df["w"] = 1.0
    df.loc[:4, "w"] = 0.0
    df.loc[5:7, "w"] = np.nan
    r = one(df, weights="w")
    assert r["n"] == 200 - 8 and r["n_missing_dropped"] == 8


def test_weight_column_cannot_double_as_a_covariate():
    from scienceunbound.schema import validate_plan
    h = Hypothesis(id="H1", label="x", outcome="out", weights="x", covariates=["x"])
    assert any("weight column" in p for p in validate_plan(plan_for(h), ["arm", "y", "x"]))
