"""Synthetic demo study with PLANTED truth. Used by the demo button, the tests and the coverage simulation.

Planted: info vs control raises trust by TRUE_G SD; social vs control has no effect; donations are unaffected;
a policy item responds to `info` only among Republicans. The file also carries planted identifiers so the privacy
audit can be tested: a response id, IP, timestamps, a contact e-mail and a free-text comment that are BLANK for the first
rows (optional questions), and a zip x age x gender combination that singles people out.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import Exclusion, Hypothesis, Outcome, Plan

TRUE_G = {"info": 0.40, "social": 0.0}
PLANTED_PII = ["ResponseId", "IPAddress", "StartDate", "RecipientEmail", "open_comment", "participant_code"]


def make_demo(n: int = 1200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    arm = rng.choice(["control", "info", "social"], size=n, p=[0.34, 0.33, 0.33])
    party = rng.choice(["Democrat", "Republican", "Independent"], size=n, p=[0.4, 0.35, 0.25])
    age = np.clip(rng.normal(44, 15, n).round(), 18, 88).astype(int)
    gender = rng.choice(["Woman", "Man", "Non-binary"], size=n, p=[0.5, 0.47, 0.03])
    zipc = rng.choice([f"{z}" for z in range(19101, 19140)], size=n)
    latent = rng.normal(0, 1, n)
    shift = np.where(arm == "info", TRUE_G["info"], 0.0) + np.where(arm == "social", TRUE_G["social"], 0.0)
    items = {}
    for i in range(1, 5):
        raw = 4.2 + 1.1 * (0.75 * latent + 0.66 * rng.normal(0, 1, n) + shift * 0.78)
        items[f"trust_{i}"] = np.clip(np.round(raw), 1, 7).astype(int)
    donate = np.clip(rng.gamma(2.0, 12.0, n) + 2 * latent, 0, 100).round(1)
    het = np.where((arm == "info") & (party == "Republican"), 0.9, 0.0)
    policy = np.clip(np.round(4.0 + 1.2 * rng.normal(0, 1, n) + het), 1, 7).astype(int)
    attention = (rng.random(n) > 0.07).astype(int)
    finished = (rng.random(n) > 0.03).astype(int)
    df = pd.DataFrame({
        "ResponseId": [f"R_{rng.integers(16**8, 16**9):x}{rng.integers(16**7, 16**8):x}"[:17].ljust(17, "x") for _ in range(n)],
        "IPAddress": [f"{rng.integers(11, 220)}.{rng.integers(0, 255)}.{rng.integers(0, 255)}.{rng.integers(1, 254)}" for _ in range(n)],
        "StartDate": pd.date_range("2026-03-02 09:00", periods=n, freq="7min").strftime("%Y-%m-%d %H:%M:%S"),
        "Finished": finished, "attention": attention, "condition": arm,
        "party": party, "age": age, "gender": gender, "zip": zipc,
        "policy": policy, "donate": donate, **items,
    })
    contact = [f"person{i}@example.org" if (i >= 8 and rng.random() < 0.7) else np.nan for i in range(n)]
    comment = [("My neighbour Maria Lopez on Elm Street told me about this study, so I joined." if (i >= 8 and rng.random() < 0.6) else np.nan)
               for i in range(n)]
    df["RecipientEmail"] = contact
    df["open_comment"] = comment
    df["participant_code"] = [f"P{100000 + i * 7919 % 899999}" for i in range(n)]
    return df


def demo_plan() -> Plan:
    return Plan(
        title="Does an informational message raise trust? (synthetic demo)",
        slug="demo-info-trust", authors=["ScienceUnbound demo"],
        summary="Synthetic data with planted effects, used to demonstrate the pipeline. Nothing here is an empirical finding.",
        design="randomized", arm_column="condition", control_level="control",
        arm_labels={"control": "Control", "info": "Information", "social": "Social norm"},
        outcomes=[
            Outcome(name="trust_index", items=[f"trust_{i}" for i in range(1, 5)], kind="index"),
            Outcome(name="donation", items=["donate"], kind="single"),
            Outcome(name="policy_item", items=["policy"], kind="single"),
        ],
        hypotheses=[
            Hypothesis(id="H1", label="Information raises trust", outcome="trust_index", direction="positive",
                       covariates=["party"], construct="institutional trust", sesoi=0.2),
            Hypothesis(id="H2", label="Information raises donations", outcome="donation", direction="positive",
                       covariates=["party"], construct="prosocial behaviour", sesoi=0.2),
            Hypothesis(id="H3", label="The information effect on the policy item differs by party", outcome="policy_item",
                       moderator="party", levels=["info"], construct="policy support"),
            Hypothesis(id="E1", label="Exploratory: do the messages move the policy item overall?", outcome="policy_item",
                       confirmatory=False, construct="policy support", sesoi=0.2),
        ],
        exclusions=[Exclusion(column="Finished", op="!=", value=1, reason="Did not finish the survey"),
                    Exclusion(column="attention", op="!=", value=1, reason="Failed the attention check")],
        multiplicity="holm", population="Synthetic respondents", data_collected_through="2026-03-31",
    )
