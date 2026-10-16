from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from .. import library as LIB
from .common import chip, footer, inject_css, render_report, studies_dir, verdict_chip

REGISTRY = "registry.json"


@st.cache_data(ttl=600, show_spinner="Reading remote studies…")
def _remote(entries_json: str):
    cards, frame, broken = LIB.remote_cards(json.loads(entries_json))
    return cards, frame, broken


def _badges(c: dict) -> str:
    out = [chip("numbers verified", "ok") if c["verified"] else chip("not verified", "warn")]
    out.append({"before_data": chip("plan locked before data", "ok"), "after_data": chip("plan locked after data", "warn"),
                "no_lock": chip("no plan lock", "grey"), "no_data_date": chip("plan locked", "info")}.get(c.get("timing_status"), ""))
    out.append(chip("data included", "info") if c["data_included"] else chip("no raw data", "grey"))
    return "".join(out)


def load_cards():
    local = LIB.scan_local(studies_dir())
    reg = LIB.load_registry(Path(studies_dir()).parent / REGISTRY)
    remote, frame, broken = ([], pd.DataFrame(), [])
    if reg:
        remote, frame, broken = _remote(json.dumps(reg))
    return local + remote, broken


def page() -> None:
    inject_css()
    st.title("Library")
    cards, broken = load_cards()
    for b in broken:
        st.warning(f"Could not reach {b}. It may be private or removed.")
    if not cards:
        st.info("No studies yet. Publish one from **New study**, or add repositories to `registry.json`.")
        footer()
        return
    q = st.text_input("Search", placeholder="title, author, construct", key="lib_q")
    c1, c2, c3 = st.columns(3)
    designs = sorted({c["design"] for c in cards if c.get("design")})
    fd = c1.multiselect("Design", designs, key="lib_design")
    fv = c2.checkbox("Numbers verified only", key="lib_ver")
    fdata = c3.checkbox("Data included", key="lib_data")
    shown = [c for c in cards if (not q or q.lower() in json.dumps([c["title"], c["authors"], c["constructs"]]).lower())
             and (not fd or c["design"] in fd) and (not fv or c["verified"]) and (not fdata or c["data_included"])]
    st.caption(f"{len(shown)} of {len(cards)} studies")
    sel = st.session_state.get("lib_open")
    if sel:
        card = next((c for c in cards if c["slug"] == sel), None)
        if card:
            _detail(card, cards)
            return
    for c in sorted(shown, key=lambda x: x.get("created") or "", reverse=True):
        with st.container(border=True):
            st.markdown(f"### {c['title']}")
            st.caption(f"{', '.join(c['authors'])} · {c['created']} · {c['n']} respondents · {c['design']}")
            st.markdown(_badges(c) + "".join(chip(f"{k} {v}", "grey") for k, v in c["verdicts"].items()), unsafe_allow_html=True)
            if c["constructs"]:
                st.caption("Constructs: " + ", ".join(c["constructs"]))
            st.button("Open", key=f"open_{c['slug']}", on_click=lambda s=c["slug"]: st.session_state.__setitem__("lib_open", s))
    footer()


def _detail(card: dict, cards: list[dict]) -> None:
    st.button("← All studies", key="lib_back", on_click=lambda: st.session_state.pop("lib_open", None))
    st.markdown(_badges(card), unsafe_allow_html=True)
    where = card["where"]
    if where.startswith("https://"):
        st.markdown(f"[Open on GitHub]({where})")
        owner_repo = where.split("github.com/")[1].split("/tree/")[0]
        ref_path = where.split("/tree/")[1]
        ref, path = ref_path.split("/", 1)
        base = f"https://raw.githubusercontent.com/{owner_repo}/{ref}/{path}"
        md = LIB._get(f"{base}/report.md", None)
        if md:
            import httpx
            def img(p):
                data = LIB._get(f"{base}/{p}", None)
                return data
            render_report(md.decode("utf-8"), img)
        else:
            st.info("The report could not be loaded.")
    else:
        root = Path(where)
        md = (root / "report.md").read_text(encoding="utf-8") if (root / "report.md").exists() else ""
        render_report(md, lambda p: (root / p).read_bytes() if (root / p).exists() else None)
        files = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for k, v in files.items():
                z.writestr(k, v)
        st.download_button("Download this package (.zip)", buf.getvalue(), f"{card['slug']}.zip", "application/zip", key="lib_zip")
    sim = LIB.similar(card, cards)
    if sim:
        st.subheader("Related studies")
        for score, o in sim:
            st.markdown(f"- {o['title']} (shared constructs: {', '.join(set(map(str.lower, o['constructs'])) & set(map(str.lower, card['constructs'])))})")
