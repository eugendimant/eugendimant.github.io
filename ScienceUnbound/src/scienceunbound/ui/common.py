"""Shared UI pieces: state, styling, small components."""
from __future__ import annotations

import os
import re
from pathlib import Path

import streamlit as st

from .. import __version__
from ..credits import DEFAULT_REPO, ORIGINATOR, ORIGINATOR_PROJECT, ORIGINATOR_REPO
from ..schema import Plan

REPO_ROOT = Path(__file__).resolve().parents[3]
STEPS = ["1 Data", "2 Privacy", "3 Plan", "4 Analyze", "5 Report", "6 Publish"]

CSS = """
<style>
.block-container {max-width: 1080px; padding-top: 2.2rem;}
h1, h2, h3 {letter-spacing: -0.01em;}
.su-hero h1 {font-size: 2.5rem; line-height: 1.1; margin-bottom: .4rem;}
.su-lead {font-size: 1.15rem; color: #3b4a45; max-width: 46rem;}
.su-card {border: 1px solid #dbe4e1; border-radius: 12px; padding: 1rem 1.1rem; background: #fff; height: 100%;}
.su-card h4 {margin: 0 0 .3rem 0; font-size: 1.02rem;}
.su-muted {color: #5b6b66; font-size: .92rem;}
.su-chip {display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600; margin: 0 6px 4px 0; border: 1px solid transparent;}
.su-ok {background: #e3f4ec; color: #14573f; border-color: #b9e2cf;}
.su-info {background: #e6effa; color: #1e4c85; border-color: #c4d8f0;}
.su-warn {background: #fff1d6; color: #7a4a00; border-color: #f2d9a6;}
.su-bad {background: #fde7e4; color: #8f1f13; border-color: #f4c3bd;}
.su-grey {background: #eef1f0; color: #43524d; border-color: #d9e0de;}
.su-credit {border-left: 4px solid #1b7f5c; background: #f3f6f5; padding: .7rem 1rem; border-radius: 0 8px 8px 0; font-size: .95rem;}
.su-step-note {background:#f3f6f5; border-radius:10px; padding:.7rem 1rem; margin:.2rem 0 1rem 0;}
div[data-testid="stMetricValue"] {font-size: 1.7rem;}
</style>
"""

VERDICT_CHIP = {"supported": ("su-ok", "supported"), "equivalent": ("su-info", "equivalent to zero"),
                "inconclusive": ("su-grey", "inconclusive"), "opposite": ("su-bad", "opposite direction")}


def chip(text: str, kind: str = "grey") -> str:
    return f'<span class="su-chip su-{kind}">{text}</span>'


def verdict_chip(v: str) -> str:
    cls, label = VERDICT_CHIP.get(v, ("su-grey", v))
    return f'<span class="su-chip {cls}">{label}</span>'


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def secret(name: str, default: str = "") -> str:
    """Streamlit secret or environment variable; never raises when no secrets file exists."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


def is_hosted() -> bool:
    return secret("SU_MODE", "local").lower() == "hosted"


def studies_dir() -> Path:
    return Path(os.environ.get("SU_STUDIES_DIR") or REPO_ROOT / "studies")


def default_repo() -> str:
    return secret("SU_GITHUB_REPO", DEFAULT_REPO)


def fresh_state() -> dict:
    return {"step": 0, "df": None, "meta": {}, "filename": "", "demo": False, "priv": None, "drop": [], "keep_reason": {},
            "quasi": [], "k": 5, "kres": None, "use_k": True, "clean": None, "plan": Plan(), "lock": None, "result": None,
            "package": None, "narrative": None, "include_data": False, "llm": {"provider": "none"}, "published": None,
            "generated_on": None}


def S() -> dict:
    if "su" not in st.session_state:
        st.session_state["su"] = fresh_state()
    return st.session_state["su"]


def reset() -> None:
    st.session_state["su"] = fresh_state()
    st.session_state.pop("su_nav", None)


def credit_box() -> None:
    st.markdown(
        f'<div class="su-credit">The idea of turning unpublished projects into checked, citable research reports comes from '
        f'<b>{ORIGINATOR}</b>, who built <a href="{ORIGINATOR_REPO}" target="_blank">{ORIGINATOR_PROJECT}</a>. '
        f'ScienceUnbound is an independent re-implementation and shares no code with it.</div>', unsafe_allow_html=True)


def footer() -> None:
    st.divider()
    st.caption(f"ScienceUnbound {__version__} · MIT licence · idea: {ORIGINATOR} ({ORIGINATOR_PROJECT})")


_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def render_report(md: str, load_image) -> None:
    """Show a report. Relative image links are loaded by `load_image(path) -> bytes | None`, because markdown cannot read them."""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)         # markers for the verifier; Streamlit would print them
    pos = 0
    for m in _IMG.finditer(md):
        st.markdown(md[pos:m.start()])
        data = load_image(m.group(2))
        if data:
            st.image(data, caption=m.group(1), width="stretch")
        pos = m.end()
    st.markdown(md[pos:])
