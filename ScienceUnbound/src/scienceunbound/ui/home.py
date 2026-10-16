from __future__ import annotations

import streamlit as st

from .common import credit_box, footer, inject_css, is_hosted, studies_dir
from .. import library as LIB


def page() -> None:
    inject_css()
    st.markdown('<div class="su-hero"><h1>Open the file drawer.</h1>'
                '<p class="su-lead">Turn a finished study that never got published into a checked, citable report. '
                'Every number is verified against its table, identifiers never leave your control, and the plan is locked before the data is read.</p></div>',
                unsafe_allow_html=True)
    c1, c2, _ = st.columns([1.5, 1.6, 5])
    if c1.button("Start a new study", type="primary", key="home_start"):
        st.switch_page(st.session_state["su_pages"]["workbench"])
    if c2.button("Browse the library", key="home_lib"):
        st.switch_page(st.session_state["su_pages"]["library"])
    st.write("")
    a, b, c = st.columns(3, gap="medium")
    a.markdown('<div class="su-card"><h4>1 · Bring a CSV and a plan</h4><p class="su-muted">Qualtrics, Stata, Excel or CSV. Describe your outcomes and tests in a form, or paste your pre-analysis plan.</p></div>', unsafe_allow_html=True)
    b.markdown('<div class="su-card"><h4>2 · Check privacy and statistics</h4><p class="su-muted">Every cell is scanned. Re-identification risk is measured. Effects come with confidence intervals, multiple-testing correction and equivalence tests for null results.</p></div>', unsafe_allow_html=True)
    c.markdown('<div class="su-card"><h4>3 · Publish a verified report</h4><p class="su-muted">An independent script checks every number in the text. One click commits the package to your GitHub repository.</p></div>', unsafe_allow_html=True)
    st.write("")
    cards = LIB.scan_local(studies_dir())
    if cards:
        st.subheader("In the library")
        for card in cards[:3]:
            st.markdown(f"**{card['title']}** · {card['n']} respondents · {sum(card['verdicts'].values())} confirmatory estimates")
    st.write("")
    credit_box()
    footer()
