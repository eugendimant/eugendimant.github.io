from __future__ import annotations

import streamlit as st

from .. import __version__
from ..credits import NOT_AFFILIATED, ONE_LINE, ORIGINATOR, ORIGINATOR_PROJECT, ORIGINATOR_REPO
from .common import credit_box, footer, inject_css

IMPROVEMENTS = [
    ("Privacy audit", "Scans every cell of every column. The original reads the header and the first five rows, so optional columns that are blank at the top slip through.",
     "Full-file scan, plus re-identification risk (k-anonymity) with automatic generalisation, and a final re-scan of every file before commit."),
    ("Verified numbers", "A language model is asked to check the report.",
     "An independent script checks every number against the result tables, binds each result line to its own table row, and checks that no estimate is left out."),
    ("Plan integrity", "A model reads the plan text; tags come from its parse.",
     "The plan is structured data. It is locked with a SHA-256 fingerprint; deviations are listed field by field; timing against data collection is checked."),
    ("Null results", "Estimate, standard error and p-value.",
     "Effect sizes with intervals, Holm or Benjamini-Hochberg correction, equivalence tests against a smallest effect of interest, and the smallest effect the study could detect."),
    ("Pooling", "Reports are not designed to be combined.",
     "Hedges g and r in a fixed schema; a random-effects meta-analysis across the library."),
    ("No generated code", "Model-written Python runs on the author's machine; exclusions are expression strings.",
     "All analysis is fixed, tested code. Exclusions are structured rules. Models only write prose and never numbers."),
    ("Reproducibility", "Outputs must be byte-identical.",
     "Tolerance-based re-run, hash manifest, recorded environment, and a forged-results test."),
    ("Any design", "Survey experiments from Qualtrics.",
     "Randomized and observational designs, moderation, clustered errors, continuous predictors; CSV, Stata, Excel."),
    ("Interface", "Command line, a static site and server admin by curl.",
     "A guided Streamlit app, no server to run, and a library that lives in GitHub files."),
    ("Follow-up planning", "Follow-up designs drafted by a model.",
     "Sample sizes from the data, including shrunken effects, plus robustness across every defensible specification."),
]


def page() -> None:
    inject_css()
    st.title("About ScienceUnbound")
    credit_box()
    st.markdown(f"""
**Why this exists.** Many finished studies never appear in print, which distorts what the literature seems to show. 
{ORIGINATOR} built {ORIGINATOR_PROJECT} as a public place for such work, with an automated pipeline that turns a study into a checked report.
ScienceUnbound is a separate implementation of that idea for use with your own research, hosted from your own GitHub repository.

{NOT_AFFILIATED}
""")
    st.subheader("What is different")
    st.dataframe([{"Area": a, "Original approach": o, "ScienceUnbound": n} for a, o, n in IMPROVEMENTS], hide_index=True, width="stretch")
    st.caption("The comparison with the original describes its source code as read on 2026-10-16. It is a design comparison, not a verdict on the original's usefulness.")
    st.subheader("Privacy model")
    st.markdown("""
- **Local mode (default).** Your file stays on your computer.
- **Hosted mode.** The server process holds uploaded files in memory. Use it for de-identified data only.
- **AI features are optional.** A model sees column names, your plan text and the structure of results. It never sees a data row and never writes a number.
- **Nothing is published unless you press the button.** The GitHub token is kept in memory for the session or read from a secret; it is never written to disk.
""")
    st.subheader("What it cannot do")
    st.markdown("""
- It does not replace peer review. A report says what the data show under the plan; it does not judge whether the plan was good.
- Verification proves that every number comes from the tables. It does not prove that the tables are right for your design.
- A lock time created by the app is self-asserted until it is committed to GitHub.
- Survey weights, multilevel models and non-linear outcome models are not supported in this version.
""")
    st.subheader("Run it yourself")
    st.code("git clone https://github.com/eugendimant/ScienceUnbound\ncd ScienceUnbound\npip install -r requirements.txt\nstreamlit run streamlit_app.py", language="bash")
    st.caption(f"Version {__version__}. Idea and first implementation: {ORIGINATOR}, {ORIGINATOR_REPO}")
    footer()
