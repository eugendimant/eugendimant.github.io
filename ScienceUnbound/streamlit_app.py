"""ScienceUnbound entry point. Run: streamlit run streamlit_app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="ScienceUnbound", page_icon="🔓", layout="wide", initial_sidebar_state="auto")

from scienceunbound.ui import about, home, library, meta, workbench  # noqa: E402

pages = {
    "home": st.Page(home.page, title="Home", icon="🏠", default=True),
    "workbench": st.Page(workbench.page, title="New study", icon="🧪", url_path="new-study"),
    "library": st.Page(library.page, title="Library", icon="📚", url_path="library"),
    "meta": st.Page(meta.page, title="Meta-analysis", icon="📊", url_path="meta-analysis"),
    "about": st.Page(about.page, title="About & credits", icon="ℹ️", url_path="about"),
}
st.session_state["su_pages"] = pages
st.navigation(list(pages.values())).run()
