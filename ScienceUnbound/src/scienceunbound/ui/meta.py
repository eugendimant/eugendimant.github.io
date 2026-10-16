from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from .. import figures as FIG
from .. import library as LIB
from .. import meta as META
from .common import footer, inject_css, studies_dir


def page() -> None:
    inject_css()
    st.title("Meta-analysis")
    st.caption("Pools confirmatory effects of the same construct across the studies in the library, with a random-effects model. "
               "Interaction and exploratory estimates are never pooled. Each study contributes one estimate per construct; "
               "'excluded' counts the further estimates from the same study that were left out because they are not independent.")
    eff = LIB.local_effects(studies_dir())
    reg = LIB.load_registry(Path(studies_dir()).parent / "registry.json")
    if reg:
        from .library import _remote
        _, frame, _ = _remote(json.dumps(reg))
        if len(frame):
            eff = pd.concat([eff, frame], ignore_index=True)
    if eff.empty:
        st.info("No studies in the library yet.")
        footer()
        return
    tab = META.meta_by_construct(eff)
    if tab.empty:
        st.info("Pooling needs confirmatory estimates with the same construct tag from at least two different studies.")
        footer()
        return
    st.warning("A library of studies that authors chose to publish can still be a selected sample. "
               "Treat pooled estimates from a few studies as descriptive, not definitive.", icon="⚠️")
    show = tab.copy()
    show["effect"] = [f"{r.pooled:.2f} [{r.ci_low:.2f}, {r.ci_high:.2f}]" for r in show.itertuples()]
    show["excluded"] = show["dependent_excluded"]
    show["I²"] = (show["I2"] * 100).round(0).astype(int).astype(str) + "%"
    st.dataframe(show[["construct", "metric", "k", "studies", "effect", "I²", "Q_p", "excluded"]].rename(columns={"k": "estimates"}), hide_index=True,
                 width="stretch")
    pick = st.selectbox("Show the forest plot for", [f"{r.construct} ({r.metric})" for r in tab.itertuples()], key="meta_pick")
    construct, metric = pick.rsplit(" (", 1)[0], pick.rsplit("(", 1)[1].rstrip(")")
    d = META.pool_frame(eff, metric)
    d = d[d["construct"] == construct].groupby("study", sort=False).head(1)
    res = META.random_effects(d["yi"], d["sei"])
    rows = pd.DataFrame({"label": d["study"].astype(str) + " · " + d["analysis_id"].astype(str), "yi": d["yi"],
                         "lo": d["yi"] - 1.96 * d["sei"], "hi": d["yi"] + 1.96 * d["sei"]})
    img = FIG.meta_forest(rows, res, "Fisher z" if metric == "r" else "Hedges g")
    if img:
        st.image(img, width="stretch")
    eg = META.egger(d["yi"], d["sei"])
    st.caption(f"Heterogeneity: tau² {res['tau2']:.3f}, I² {res['I2'] * 100:.0f}%, Q test p {res['Q_p']:.3f}. "
               + (f"Small-study asymmetry (Egger) p {eg['p']:.3f}." if eg else "Small-study asymmetry needs at least ten estimates."))
    footer()
