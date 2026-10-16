import math

import numpy as np
import pandas as pd
from statsmodels.stats.meta_analysis import combine_effects

from scienceunbound import meta as M


def test_random_effects_matches_statsmodels_dersimonian_laird():
    rng = np.random.default_rng(3)
    se = rng.uniform(0.08, 0.3, 12)
    y = rng.normal(0.25, 0.35, 12) + rng.normal(0, se)          # real between-study heterogeneity
    mine = M.random_effects(y, se)
    ref = combine_effects(y, se**2, method_re="dl", use_t=False)
    assert ref.tau2 > 0
    assert math.isclose(mine["tau2"], ref.tau2, rel_tol=1e-9)
    # the pooled estimate does not depend on the CI adjustment
    assert math.isclose(mine["pooled"], ref.mean_effect_re, rel_tol=1e-9)
    assert mine["ci_low"] < mine["pooled"] < mine["ci_high"]
    assert 0 <= mine["I2"] <= 1 and mine["pi_low"] < mine["ci_low"]


def test_negative_dl_variance_is_truncated_at_zero():
    rng = np.random.default_rng(3)
    se = rng.uniform(0.08, 0.3, 12)
    y = rng.normal(0.25, 0.15, 12) + rng.normal(0, se)
    ref = combine_effects(y, se**2, method_re="dl", use_t=False)
    assert ref.tau2 < 0 and M.random_effects(y, se)["tau2"] == 0.0


def test_homogeneous_studies_have_zero_tau():
    y = np.array([0.30, 0.31, 0.29, 0.30]); se = np.array([0.1, 0.1, 0.1, 0.1])
    r = M.random_effects(y, se)
    assert r["tau2"] == 0 and math.isclose(r["pooled"], 0.30, abs_tol=0.01)


def test_hartung_knapp_ci_is_never_narrower_than_the_normal_dl_ci():
    rng = np.random.default_rng(4)
    for _ in range(50):
        se = rng.uniform(0.05, 0.3, 6); y = rng.normal(0.2, 0.2, 6)
        r = M.random_effects(y, se)
        ws = 1 / (se**2 + r["tau2"])
        z_half = 1.96 / math.sqrt(ws.sum())
        assert (r["ci_high"] - r["ci_low"]) / 2 >= z_half - 1e-9


def test_single_study_returns_its_own_estimate_without_a_ci():
    r = M.random_effects([0.4], [0.1])
    assert r["k"] == 1 and r["pooled"] == 0.4 and math.isnan(r["ci_low"])


def test_egger_needs_ten_and_detects_planted_asymmetry():
    assert M.egger(np.ones(5), np.ones(5)) is None
    rng = np.random.default_rng(5)
    se = rng.uniform(0.05, 0.4, 40)
    y = 0.4 * se / 0.2 + rng.normal(0, 0.03, 40)          # small studies report larger effects
    assert M.egger(y, se)["p"] < 0.01


def _effects(rows):
    cols = ["study", "analysis_id", "construct", "confirmatory", "es_metric", "es", "es_se"]
    return pd.DataFrame(rows, columns=cols)


def test_pooling_is_per_construct_and_metric_and_skips_interactions_and_exploratory():
    rows = [("s1", "H1", "trust", True, "g", 0.30, 0.10), ("s2", "H1", "trust", True, "g", 0.20, 0.12),
            ("s3", "H1", "trust", True, "g", 0.25, 0.09), ("s4", "H1", "trust", False, "g", 5.0, 0.01),
            ("s5", "H3", "trust", True, "g_int", 9.0, 0.01), ("s1", "H2", "donation", True, "g", 0.0, 0.1),
            ("s6", "H4", "trust", True, "r", 0.3, 0.05), ("s7", "H4", "trust", True, "r", 0.2, 0.05)]
    out = M.meta_by_construct(_effects(rows))
    g = out[(out.construct == "trust") & (out.metric == "g")].iloc[0]
    assert g["k"] == 3 and 0.2 < g["pooled"] < 0.3                 # the 5.0 exploratory and 9.0 interaction rows were excluded
    r = out[(out.construct == "trust") & (out.metric == "r")].iloc[0]
    assert 0.2 < r["pooled"] < 0.3 and abs(r["pooled"]) < 1
    assert "donation" not in set(out.construct)                    # a single estimate is never pooled


def test_two_contrasts_from_one_study_are_not_pooled_as_independent_studies():
    rows = [("s1", "H1:a", "trust", True, "g", 0.30, 0.10), ("s1", "H1:b", "trust", True, "g", 0.28, 0.10)]
    assert M.meta_by_construct(_effects(rows)).empty                # one study is not a meta-analysis
    rows += [("s2", "H1", "trust", True, "g", 0.20, 0.10)]
    out = M.meta_by_construct(_effects(rows))
    r = out.iloc[0]
    assert r["k"] == 2 and r["studies"] == 2 and r["dependent_excluded"] == 1
    assert math.isclose(r["pooled"], 0.25, abs_tol=1e-9)           # the first contrast of s1, not the average of three
