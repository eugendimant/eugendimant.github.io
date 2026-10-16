"""The six-step workbench: Data, Privacy, Plan, Analyze, Report, Publish."""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import zipfile

import pandas as pd
import streamlit as st

from .. import figures as FIG
from .. import llm as LLM
from .. import privacy as PRIV
from .. import registration as REG
from .. import report as REP
from ..analyze import run_analysis
from ..demo import demo_plan, make_demo
from ..github_publish import GitHubError, publish_files
from ..ingest import infer_dictionary, normalize, read_table
from ..package import build_package, write_package
from ..schema import (EXCLUSION_OPS, SE_TYPES, Exclusion, Hypothesis, Outcome, Plan, canon_level, plan_from_dict, plan_hash,
                      plan_to_dict, validate_plan)
from .common import (STEPS, S, chip, default_repo, inject_css, is_hosted, reset, secret, studies_dir, render_report, verdict_chip)

QUASI_HINT = re.compile(r"age|gender|sex|race|ethnic|educ|income|state|region|zip|postal|country|occupation|party|relig|marital|birth|year|city",
                        re.I)
ARM_HINT = re.compile(r"cond|arm|treat|group|assign|random|cell", re.I)


# ------------------------------------------------------------------ navigation
def ready(i: int) -> bool:
    s = S()
    if i == 0:
        return True
    if i == 1:
        return s["df"] is not None
    if i == 2:
        return s["clean"] is not None
    if i == 3:
        return s["clean"] is not None and not validate_plan(s["plan"], list(s["clean"].columns))
    if i == 4:
        return s["result"] is not None
    return s["package"] is not None


def go(i: int) -> None:
    S()["step"] = i
    st.session_state["su_nav"] = STEPS[i]


def _on_nav() -> None:
    s = S()
    sel = st.session_state.get("su_nav")
    if sel is None or sel not in STEPS or not ready(STEPS.index(sel)):
        st.session_state["su_nav"] = STEPS[s["step"]]
        st.session_state["su_nav_blocked"] = True
        return
    s["step"] = STEPS.index(sel)


def nav() -> None:
    s = S()
    st.session_state.setdefault("su_nav", STEPS[s["step"]])
    st.segmented_control("Step", STEPS, key="su_nav", on_change=_on_nav, label_visibility="collapsed", selection_mode="single")
    if st.session_state.pop("su_nav_blocked", False):
        st.toast("Finish the current step first.", icon="🔒")


def invalidate_from(step: int) -> None:
    """Throw away everything computed from this step onward."""
    s = S()
    if step <= 1:
        s.update(priv=None, drop=[], keep_reason={}, quasi=[], kres=None)
    if step <= 2:
        s["clean"] = None
    if step <= 3:
        s.update(result=None, package=None, narrative=None, published=None)
    if step <= 4:
        s.update(package=None, published=None)


def next_button(label: str, target: int, disabled: bool = False, key: str | None = None) -> None:
    st.button(label, type="primary", disabled=disabled, on_click=go, args=(target,), key=key or f"next_{target}")


def back_button(target: int) -> None:
    st.button("← Back", on_click=go, args=(target,), key=f"back_{target}")


# ------------------------------------------------------------------ step 1: data
def _load(df: pd.DataFrame, meta: dict, demo: bool) -> None:
    invalidate_from(1)
    s = S()
    s.update(df=df, meta=meta, filename=meta.get("filename", ""), demo=demo)
    rep = PRIV.audit_dataframe(df)
    s["priv"] = rep
    s["drop"] = rep.to_drop()
    s["quasi"] = [c for c in df.columns if QUASI_HINT.search(c) and c not in s["drop"] and 2 <= df[c].nunique() <= 200][:4]
    if demo:
        s["plan"] = demo_plan()
        s["plan"].data_collected_through = dt.date.today().isoformat()     # a demo should not open on a false alarm
        s["lock"] = None
    else:
        s["plan"] = Plan()
        s["lock"] = None


def step_data() -> None:
    s = S()
    if is_hosted():
        st.warning("**Hosted app.** A file you upload is processed in this server's memory. For raw data that contains identifiers, "
                   "run ScienceUnbound on your own computer (see About). Use this hosted version with data that is already de-identified.",
                   icon="🌐")
    else:
        st.success("**Running on your computer.** Your file is not sent anywhere. Only the optional AI features use the network.", icon="🔒")
    c1, c2 = st.columns([3, 2], gap="large")
    with c1:
        up = st.file_uploader("Upload your study data", type=["csv", "tsv", "dta", "xlsx"], key="su_upload",
                              help="CSV, TSV, Stata (.dta) or Excel. Qualtrics exports with the three-row header work as they are.")
        if up is not None and (s["filename"], s["meta"].get("size")) != (up.name, up.size):
            try:
                df, meta = read_table(up)
                meta["size"] = up.size
                _load(df, meta, demo=False)
                st.rerun()
            except Exception as e:  # shown to the user, nothing is stored
                st.error(f"Could not read this file: {e}")
    with c2:
        st.markdown("**No data at hand?**")
        if st.button("Load the synthetic demo study", key="demo", help="Simulated survey experiment with planted effects and planted identifiers."):
            df = normalize(make_demo())
            _load(df, {"filename": "demo_data.csv", "qualtrics": False, "labels": {}, "sha256": ""}, demo=True)
            st.rerun()
    df = s["df"]
    if df is None:
        st.info("Upload a file or load the demo to begin.")
        return
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Rows", f"{len(df):,}")
    m2.metric("Columns", df.shape[1])
    m3.metric("Qualtrics header", "found" if s["meta"].get("qualtrics") else "no")
    m4.metric("Cells to scan", f"{df.size:,}")
    st.caption("Below: the columns of your file. No cell values are shown before the privacy check.")
    d = infer_dictionary(df, s["meta"].get("labels"))
    st.dataframe(d, hide_index=True, width="stretch", height=min(380, 38 + 35 * len(d)),
                 column_config={"missing_pct": st.column_config.ProgressColumn("missing %", min_value=0, max_value=100, format="%.1f")})
    next_button("Continue to the privacy check →", 1, key="to_privacy")


# ------------------------------------------------------------------ step 2: privacy
def _finish_privacy() -> None:
    """Runs as a button callback, so it may change the navigation widget's state."""
    s = S()
    base = s["df"].drop(columns=s["drop"])
    use = bool(s["kres"] and s["use_k"])
    d = s["kres"]["df"] if use else base
    s["clean"] = normalize(d)
    final = PRIV.k_anonymity(s["clean"], [q for q in s["quasi"] if q in s["clean"].columns], s["k"]) if s["quasi"] else {}
    s["priv_summary"] = {"dropped": list(s["drop"]), "kept": dict(s["keep_reason"]), "k_stats": final,
                         "k_actions": (s["kres"]["actions"] if use else ([] if s["quasi"] else None))}
    invalidate_from(3)
    go(2)


def step_privacy() -> None:
    s = S()
    df, rep = s["df"], s["priv"]
    st.markdown('<div class="su-step-note">Every cell of every column was scanned for identifiers, free text and exact timestamps. '
                'Findings show column names and reasons, never the values.</div>', unsafe_allow_html=True)
    m1, m2, m3 = st.columns(3)
    m1.metric("Cells scanned", f"{rep.cells_scanned:,}")
    m2.metric("Columns flagged", len(rep.findings))
    m3.metric("Columns to remove", len(s["drop"]))
    flagged = [f for f in rep.findings]
    if flagged:
        st.subheader("Flagged columns")
        tbl = pd.DataFrame({"Remove": [f.column in s["drop"] for f in flagged], "Column": [f.column for f in flagged],
                            "Why it was flagged": [f.reason for f in flagged], "Matching cells": [str(f.hits) if f.hits else "" for f in flagged]})
        edited = st.data_editor(tbl, hide_index=True, width="stretch", key="su_flag_editor",
                                disabled=["Column", "Why it was flagged", "Matching cells"],
                                column_config={"Remove": st.column_config.CheckboxColumn(help="Untick to keep a column. You must then say why it is safe.")})
        s["drop"] = [c for c, r in zip(edited["Column"], edited["Remove"]) if r]
        kept = [f.column for f in flagged if f.action == "drop" and f.column not in s["drop"]]
        for c in kept:
            s["keep_reason"][c] = st.text_input(f"Why is **{c}** safe to keep?", s["keep_reason"].get(c, ""), key=f"keep_{c}")
        s["keep_reason"] = {c: v for c, v in s["keep_reason"].items() if c in kept}
    else:
        st.success("No identifier-like columns found.")
    remaining = [c for c in df.columns if c not in s["drop"]]
    st.subheader("Can people be re-identified from ordinary columns?")
    st.caption("Age, gender and region can single a person out in combination. Choose the columns an outsider could know. "
               "Every combination should be shared by at least k respondents.")
    cands = [c for c in remaining if df[c].nunique() <= 500]
    s["quasi"] = st.multiselect("Quasi-identifiers", cands, [c for c in s["quasi"] if c in cands], key="su_quasi",
                                help="Columns an outsider could know about a respondent.")
    s["k"] = st.slider("Smallest group allowed (k)", 2, 20, s["k"], key="su_k",
                       help="k = 5 means every combination of these columns describes at least 5 respondents.")
    base = df.drop(columns=s["drop"])
    stats = PRIV.k_anonymity(base, s["quasi"], s["k"])
    if s["quasi"]:
        c1, c2, c3 = st.columns(3)
        c1.metric("Smallest group", stats["min_k"])
        c2.metric("Respondents in groups below k", f"{stats['share_below_k'] * 100:.1f}%")
        c3.metric("Unique respondents", stats["unique_rows"])
        if stats["min_k"] < s["k"]:
            st.warning("Some combinations are rarer than k. Generalise them, or do not publish respondent-level data.")
            if st.button("Generalise automatically", key="gen_k"):
                out, actions, fin = PRIV.enforce_k(base, s["quasi"], s["k"])
                s["kres"] = {"df": out, "actions": actions, "stats": fin, "quasi": list(s["quasi"]), "k": s["k"], "drop": list(s["drop"])}
        else:
            st.success("Every combination meets k.")
    else:
        st.info("No quasi-identifiers selected, so re-identification risk is not assessed.")
    kres = s["kres"]
    if kres and (kres["quasi"], kres["k"], kres["drop"]) == (list(s["quasi"]), s["k"], list(s["drop"])):
        st.markdown("**Generalisation applied**")
        for a in kres["actions"]:
            st.markdown(f"- {a}")
        f = kres["stats"]
        st.caption(f"After generalising: smallest group {f['min_k']}, respondents below k: {f['rows_below_k']}. "
                   f"Respondents kept: {len(kres['df']):,} of {len(base):,}.")
        s["use_k"] = st.toggle("Use the generalised data", s["use_k"], key="su_use_k")
    else:
        s["kres"] = None
    with st.expander("Preview de-identified rows"):
        st.dataframe((kres["df"] if (s["kres"] and s["use_k"]) else base).head(8), width="stretch")
    unresolved = [c for c in s["keep_reason"] if not s["keep_reason"][c].strip()]
    c1, c2 = st.columns([1, 6])
    with c1:
        back_button(0)
    with c2:
        st.button("Continue to the plan →", type="primary", disabled=bool(unresolved), key="to_plan", on_click=_finish_privacy)
        if unresolved:
            st.caption("Give a reason for each column you keep.")


# ------------------------------------------------------------------ step 3: plan
def _slug(t: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", t.lower())).strip("-")[:60]


def _numeric(df): return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


PROVIDERS = ["none", "ollama", "lmstudio", "anthropic", "openai_compatible"]
PROVIDER_LABEL = {"none": "None (no AI; everything else still works)", "ollama": "Ollama (local, free)",
                  "lmstudio": "LM Studio (local, free)", "anthropic": "Anthropic API (pay per use)",
                  "openai_compatible": "OpenAI-style server (OpenRouter, OpenAI, others)"}


def _llm_defaults() -> dict:
    """Deployment-level defaults from Streamlit secrets or environment variables, so a key never has to be typed into a page."""
    return {"provider": secret("SU_LLM_PROVIDER", "none"), "api_key": secret("SU_LLM_API_KEY"), "model": secret("SU_LLM_MODEL"),
            "base_url": secret("SU_LLM_BASE_URL")}


def _llm_cfg() -> LLM.LLMConfig:
    c = {**_llm_defaults(), **{k: v for k, v in S()["llm"].items() if v not in ("", None)}}
    return LLM.LLMConfig(provider=c.get("provider", "none"), api_key=c.get("api_key", ""), base_url=c.get("base_url", ""),
                         model=c.get("model", ""), budget_usd=float(c.get("budget", 0.25)),
                         price_in_per_mtok=float(c.get("price_in", 0)), price_out_per_mtok=float(c.get("price_out", 0)))


def llm_settings(key: str) -> None:
    s = S()
    c = s["llm"]
    d = _llm_defaults()
    with st.expander("AI settings (optional)"):
        st.caption("AI never sees a data row: only column names, your plan text and the ids and verdicts of results. It never writes a number. "
                   "Numbers are filled in from the tables and checked.")
        cur = c.get("provider") or d["provider"]
        prov = st.selectbox("Provider", PROVIDERS, PROVIDERS.index(cur if cur in PROVIDERS else "none"), format_func=PROVIDER_LABEL.get, key=f"{key}_prov")
        c["provider"] = prov
        if prov == "none":
            return
        local = prov in ("ollama", "lmstudio")
        if local and is_hosted():
            st.error("This app runs on a server, so 'local' would mean the server, not your computer. Run ScienceUnbound on your own computer to use a local model.")
        if not local and is_hosted() and not d["api_key"]:
            st.warning("A key typed here is sent to the server that runs this app. Prefer the secret SU_LLM_API_KEY, or run locally.")
        if prov == "anthropic" or prov == "openai_compatible":
            if d["api_key"]:
                st.caption("Using the key from the deployment secret SU_LLM_API_KEY.")
            else:
                c["api_key"] = st.text_input("API key", c.get("api_key", ""), type="password", key=f"{key}_key")
        if prov == "openai_compatible":
            c["base_url"] = st.text_input("Base URL", c.get("base_url") or d["base_url"] or "https://openrouter.ai/api/v1", key=f"{key}_url")
        if local:
            c["base_url"] = st.text_input("Server address", c.get("base_url") or LLM.LOCAL_URLS[prov], key=f"{key}_url",
                                          help="Ollama listens on port 11434 and LM Studio on port 1234 by default.")
            if st.button("Test the connection and list models", key=f"{key}_test"):
                try:
                    st.session_state[f"{key}_models"] = LLM.list_models(LLM.LLMConfig(provider=prov, base_url=c["base_url"]))
                except RuntimeError as e:
                    st.session_state[f"{key}_models"] = []
                    st.error(str(e))
            models = st.session_state.get(f"{key}_models") or []
            if models:
                st.success(f"Connected. {len(models)} model(s) available.")
                c["model"] = st.selectbox("Model", models, models.index(c["model"]) if c.get("model") in models else 0, key=f"{key}_msel")
        if not (local and st.session_state.get(f"{key}_models")):
            c["model"] = st.text_input("Model", c.get("model") or d["model"], key=f"{key}_model", help="Exact model name from your provider.")
        if not local:
            c1, c2, c3 = st.columns(3)
            c["budget"] = c1.number_input("Budget (USD)", 0.0, 50.0, float(c.get("budget", 0.25)), 0.05, key=f"{key}_bud")
            c["price_in"] = c2.number_input("Price in / M tokens", 0.0, 500.0, float(c.get("price_in", 0)), key=f"{key}_pin")
            c["price_out"] = c3.number_input("Price out / M tokens", 0.0, 500.0, float(c.get("price_out", 0)), key=f"{key}_pout")
            st.caption("Set both prices to enforce the dollar budget; otherwise at most 6 calls are made.")


def _lock_box(p: Plan, df: pd.DataFrame) -> None:
    s = S()
    lock = s["lock"]
    st.subheader("Lock the plan")
    st.caption("Lock the plan before you look at any outcome. The lock stores a SHA-256 fingerprint and a copy of the plan. "
               "Later changes are shown as deviations, field by field.")
    c1, c2 = st.columns(2)
    p.data_collected_through = c1.text_input("Data collection ended on (YYYY-MM-DD, optional)", p.data_collected_through, key="su_dcend",
                                              help="Lets the report say whether the plan was locked before data collection ended.")
    p.registration_url = c2.text_input("External registration link (optional)", p.registration_url, key="su_reg",
                                       help="OSF, AsPredicted, AEA registry. Listed in the report, not verified.")
    if p.data_collected_through and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.data_collected_through):
        st.error("Use the date format YYYY-MM-DD.")
    if st.button("Lock this plan now" if not lock else "Replace the lock with the current plan", key="do_lock"):
        s["lock"] = REG.make_lock(p)
        invalidate_from(4)
        st.rerun()
    if lock:
        intact = REG.lock_is_intact(lock)
        anchored = bool(lock.get("anchor"))
        st.markdown(chip("locked", "ok") + chip("anchored on GitHub" if anchored else "time is self-asserted",
                                                 "ok" if anchored else "warn") + chip("intact" if intact else "EDITED", "ok" if intact else "bad"),
                    unsafe_allow_html=True)
        st.caption(f"Locked {lock['locked_at']} · fingerprint `{lock['sha256'][:16]}…`")
        tags, missing = REG.tag_hypotheses(p, lock)
        changed = [t for t in tags if t["tag"] in ("deviation", "unregistered")]
        if changed or missing:
            st.warning("The plan differs from the lock. These changes will be reported as deviations.")
            for t in changed:
                if t["tag"] == "deviation":
                    st.markdown(f"**{t['id']}** differs in: " + ", ".join(f"`{d}`" for d in t["differences"]))
                    p.deviation_notes[t["id"]] = st.text_input(f"Reason for the change to {t['id']}", p.deviation_notes.get(t["id"], ""), key=f"dev_{t['id']}")
                else:
                    st.markdown(f"**{t['id']}** was added after the lock.")
            if missing:
                st.markdown("Locked but no longer in the plan: " + ", ".join(missing))
        st.download_button("Download plan.lock.json", json.dumps(lock, indent=1), "plan.lock.json", "application/json", key="dl_lock")
        token = secret("GITHUB_TOKEN") or st.session_state.get("su_ghtoken", "")
        if not anchored and token:
            if st.button("Anchor the lock on GitHub now", key="anchor", help="Commits plan.json and plan.lock.json. GitHub's commit time is an independent timestamp."):
                try:
                    out = publish_files({"plan.json": json.dumps(plan_to_dict(p), indent=1).encode(),
                                         "plan.lock.json": json.dumps(lock, indent=1).encode()},
                                        repo=default_repo(), token=token, subdir=f"studies/{p.slug}", message=f"Lock plan: {p.slug}")
                    lock["anchor"] = {"commit": out["commit_sha"], "committed_at": out["committed_at"], "url": out["commit_url"]}
                    st.rerun()
                except GitHubError as e:
                    st.error(str(e))
        elif not anchored:
            st.caption("To anchor the lock, add a GitHub token in the Publish step or as the secret GITHUB_TOKEN.")


def _finish_plan() -> None:
    invalidate_from(4)
    go(3)


def step_plan() -> None:
    s = S()
    df: pd.DataFrame = s["clean"]
    p: Plan = s["plan"]
    cols = list(df.columns)
    if s["demo"]:
        st.info("The demo plan is loaded. Change anything you like.", icon="🧪")
    # --- optional AI draft
    with st.expander("Start from your pre-analysis plan text (optional)"):
        txt = st.text_area("Paste the plan text", height=140, key="su_pap")
        llm_settings("planllm")
        cfg = _llm_cfg()
        if st.button("Draft a plan from this text", disabled=(cfg.provider == "none" or not txt.strip()), key="draft_plan"):
            try:
                drafted, problems = LLM.draft_plan(txt, cols, LLM.LLM(cfg))
                if drafted is not None:
                    drafted.title, drafted.slug, drafted.authors = p.title, p.slug, p.authors
                    s["plan"] = drafted
                    st.session_state["su_draft_problems"] = problems
                    st.rerun()
                st.error("; ".join(problems))
            except Exception as e:
                st.error(f"The draft failed: {e}")
        if st.session_state.get("su_draft_problems"):
            st.warning("Check the draft: " + "; ".join(st.session_state["su_draft_problems"]))
        up = st.file_uploader("…or load a plan JSON", type=["json"], key="su_plan_json")
        if up is not None and st.session_state.get("su_plan_loaded") != (up.name, up.size):
            try:
                s["plan"] = plan_from_dict(json.loads(up.read()))
                st.session_state["su_plan_loaded"] = (up.name, up.size)
                st.rerun()
            except Exception as e:
                st.error(f"Not a valid plan file: {e}")
    p = s["plan"]
    # --- study info
    st.subheader("Study")
    p.title = st.text_input("Title", p.title, key="su_title")
    c1, c2 = st.columns(2)
    p.slug = c1.text_input("Folder name", p.slug or _slug(p.title), key="su_slug", help="Lowercase letters, digits and hyphens. Becomes studies/<folder name>/.")
    p.authors = [a.strip() for a in c2.text_input("Authors (comma-separated)", ", ".join(p.authors), key="su_authors").split(",") if a.strip()]
    p.summary = st.text_area("One-paragraph description (optional, shown as written)", p.summary, key="su_summary", height=80)
    p.population = st.text_input("Population and sample (optional)", p.population, key="su_pop")
    # --- design
    st.subheader("Design")
    p.design = st.radio("What kind of study is this?", ["randomized", "observational"], index=["randomized", "observational"].index(p.design),
                        format_func=lambda x: {"randomized": "Randomized experiment (participants were assigned to conditions)",
                                               "observational": "Observational (no random assignment)"}[x],
                        key="su_design")
    if p.design == "randomized":
        arm_cands = [c for c in cols if df[c].nunique() <= 12 and c not in _numeric(df)[:0]]
        guess = next((c for c in arm_cands if ARM_HINT.search(c)), arm_cands[0] if arm_cands else None)
        if arm_cands:
            cur = p.arm_column if p.arm_column in arm_cands else guess
            p.arm_column = st.selectbox("Column that holds the condition", arm_cands, arm_cands.index(cur), key="su_arm")
            levels = sorted({canon_level(v) for v in df[p.arm_column].dropna().unique()})
            curc = p.control_level if p.control_level in levels else levels[0]
            p.control_level = st.selectbox("Control condition", levels, levels.index(curc), key="su_ctrl",
                                           help="Every other condition is compared with this one.")
            with st.expander("Readable names for the conditions (optional)"):
                for lv in levels:
                    lab = st.text_input(f"Name for '{lv}'", p.arm_labels.get(lv, ""), key=f"su_lab_{lv}")
                    if lab.strip():
                        p.arm_labels[lv] = lab.strip()
                    else:
                        p.arm_labels.pop(lv, None)
        else:
            st.error("No column with few distinct values to use as the condition. Choose 'observational' or check the data.")
    # --- outcomes
    st.subheader("Outcomes")
    num = _numeric(df)
    for i, o in enumerate(list(p.outcomes)):
        c1, c2 = st.columns([8, 1])
        c1.markdown(f"**{o.name}** · {'index of ' + str(len(o.items)) + ' items' if o.kind == 'index' else 'single item'} · "
                    f"`{', '.join(o.items)}`" + (f" · reversed: `{', '.join(o.reverse)}`" if o.reverse else ""))
        if c2.button("Remove", key=f"rm_out_{i}"):
            p.outcomes.pop(i)
            p.hypotheses = [h for h in p.hypotheses if h.outcome != o.name]
            st.rerun()
    with st.form("add_outcome", clear_on_submit=True):
        st.markdown("**Add an outcome**")
        c1, c2 = st.columns([2, 2])
        name = c1.text_input("Name", placeholder="trust_index")
        kind = c2.radio("Built from", ["single item", "mean of several items (index)"], horizontal=True)
        items = st.multiselect("Column(s)", num)
        c1, c2, c3 = st.columns(3)
        rev = c1.multiselect("Reverse-coded items", num, help="Needs the lowest and highest scale points.")
        lo, hi = c2.number_input("Lowest scale point", value=0.0), c3.number_input("Highest scale point", value=0.0)
        if st.form_submit_button("Add outcome"):
            o = Outcome(name=name.strip(), items=items, reverse=[r for r in rev if r in items], scale=[lo, hi] if rev else None,
                        kind="single" if kind == "single item" else "index")
            probs = [x for x in validate_plan(Plan(title="t", slug="tt", outcomes=[o], hypotheses=[Hypothesis(id="X", label="", outcome=o.name, predictor="x")]),
                                              cols + ["x"]) if x.startswith(("outcome", "every outcome"))]
            if o.name in [q.name for q in p.outcomes]:
                probs.append("An outcome with this name exists.")
            if probs:
                st.error(" ".join(probs))
            else:
                p.outcomes.append(o)
                st.rerun()
    # --- hypotheses
    st.subheader("Hypotheses and tests")
    st.caption("Confirmatory tests are corrected for multiple testing together. Exploratory tests are labelled and corrected separately.")
    if p.outcomes and p.design == "randomized" and not p.hypotheses and st.button("Add one confirmatory test per outcome", key="auto_h"):
        for i, o in enumerate(p.outcomes, 1):
            p.hypotheses.append(Hypothesis(id=f"H{i}", label=f"Condition differences in {o.name}", outcome=o.name, sesoi=0.2))
        st.rerun()
    for i, h in enumerate(list(p.hypotheses)):
        c1, c2 = st.columns([8, 1])
        c1.markdown(f"**{h.id}** {'confirmatory' if h.confirmatory else 'exploratory'} · {h.label or '(no label)'} · outcome `{h.outcome}` · "
                    f"{h.direction.replace('_', ' ')} · errors {h.se}" + (f" · covariates `{', '.join(h.covariates)}`" if h.covariates else "")
                    + (f" · moderator `{h.moderator}`" if h.moderator else "") + (f" · weights `{h.weights}`" if h.weights else "") + (f" · equivalence ±{h.sesoi}" if h.sesoi else ""))
        if c2.button("Remove", key=f"rm_h_{i}"):
            p.hypotheses.pop(i)
            st.rerun()
    if p.outcomes:
        with st.form("add_hyp", clear_on_submit=True):
            st.markdown("**Add a test**")
            c1, c2, c3 = st.columns([1, 3, 2])
            hid = c1.text_input("ID", value=f"H{len(p.hypotheses) + 1}")
            label = c2.text_input("Short description")
            outcome = c3.selectbox("Outcome", [o.name for o in p.outcomes])
            c1, c2, c3 = st.columns(3)
            pred = c1.selectbox("Predictor", ["(condition column)"] + [c for c in cols if c != p.arm_column], help="Leave as the condition column for a treatment comparison.")
            direction = c2.selectbox("Expected direction", ["two_sided", "positive", "negative"],
                                     format_func=lambda x: {"two_sided": "No direction (two-sided)", "positive": "Higher than control", "negative": "Lower than control"}[x])
            confirmatory = c3.checkbox("Confirmatory (planned in advance)", value=True)
            covs = st.multiselect("Adjust for (covariates)", [c for c in cols if c != p.arm_column])
            c1, c2, c3 = st.columns(3)
            se = c1.selectbox("Standard errors", list(SE_TYPES), help="HC2 is a safe default. Choose cluster when respondents appear in several rows.")
            cluster = c2.selectbox("Cluster column", [""] + cols)
            mod = c3.selectbox("Does the effect differ by… (moderator)", [""] + cols)
            c1, c2, c3 = st.columns(3)
            construct = c1.text_input("Construct tag (used to pool studies)", placeholder="institutional trust")
            sesoi = c2.number_input("Smallest effect that would matter (SD units; 0 = no equivalence test)", 0.0, 3.0, 0.2, 0.05)
            wcol = c3.selectbox("Survey weight column (optional)", [""] + num, help="Applied as analytic weights with robust errors.")
            if st.form_submit_button("Add test"):
                predictor = "" if pred.startswith("(") else pred
                ptype = "continuous" if (predictor and predictor in num and df[predictor].nunique() > 6) else "categorical"
                h = Hypothesis(id=hid.strip(), label=label.strip(), outcome=outcome, predictor=predictor, predictor_type=ptype,
                               direction=direction, covariates=covs, se=se, cluster=cluster, moderator=mod, confirmatory=confirmatory,
                               construct=construct.strip(), sesoi=sesoi or None, weights=wcol)
                if hid.strip() in [q.id for q in p.hypotheses]:
                    st.error("This ID exists.")
                else:
                    p.hypotheses.append(h)
                    st.rerun()
    # --- exclusions
    st.subheader("Exclusions")
    st.caption("Rows where the condition is true are removed, in this order.")
    for i, e in enumerate(list(p.exclusions)):
        c1, c2 = st.columns([8, 1])
        c1.markdown(f"Remove rows where `{e.column}` {e.op} {'' if e.value is None else '`' + str(e.value) + '`'}" + (f" · {e.reason}" if e.reason else ""))
        if c2.button("Remove", key=f"rm_e_{i}"):
            p.exclusions.pop(i)
            st.rerun()
    with st.form("add_excl", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([2, 1, 2, 3])
        ec = c1.selectbox("Column", cols)
        eo = c2.selectbox("Is", list(EXCLUSION_OPS), help="in / not_in take a comma-separated list.")
        ev = c3.text_input("Value")
        er = c4.text_input("Reason (shown in the sample table)", placeholder="Failed the attention check")
        if st.form_submit_button("Add exclusion"):
            val: object = None
            if eo in ("in", "not_in"):
                val = [x.strip() for x in ev.split(",") if x.strip()]
            elif eo not in ("isna", "notna"):
                try:
                    val = float(ev) if eo in (">", ">=", "<", "<=") else ev
                except ValueError:
                    st.error("This operator needs a number.")
                    val = None
                    eo = None
            if eo:
                p.exclusions.append(Exclusion(ec, eo, val, er.strip()))
                st.rerun()
    # --- statistics
    st.subheader("Statistics")
    c1, c2, c3 = st.columns(3)
    p.alpha = c1.select_slider("Significance level", [0.01, 0.025, 0.05, 0.10], p.alpha, key="su_alpha")
    p.multiplicity = c2.radio("Multiple-testing correction", ["holm", "bh", "none"], ["holm", "bh", "none"].index(p.multiplicity),
                              format_func=lambda x: {"holm": "Holm (recommended)", "bh": "Benjamini-Hochberg", "none": "None"}[x], key="su_mult")
    p.seed = int(c3.number_input("Random seed", 0, 2**31 - 1, p.seed, key="su_seed"))
    _lock_box(p, df)
    problems = validate_plan(p, cols)
    st.divider()
    if problems:
        st.error("To continue, fix:\n\n" + "\n".join(f"- {x}" for x in problems))
    c1, c2 = st.columns([1, 6])
    with c1:
        back_button(1)
    with c2:
        st.button("Continue to the analysis →", type="primary", disabled=bool(problems), key="to_analyze", on_click=_finish_plan)


# ------------------------------------------------------------------ step 4: analyze
def step_analyze() -> None:
    s = S()
    p: Plan = s["plan"]
    res = s["result"]
    stale = res is not None and res.plan_sha256 != plan_hash(p)
    if res is None or stale:
        if stale:
            st.warning("The plan changed since the last run.")
        st.markdown('<div class="su-step-note">Everything below is computed by fixed, tested code. '
                    'No model writes or runs code.</div>', unsafe_allow_html=True)
        if st.button("Run the analysis", type="primary", key="run"):
            with st.spinner("Estimating, adjusting for multiple tests and re-running the specification curves…"):
                try:
                    s["result"] = run_analysis(s["clean"], p, s["lock"])
                    s["package"] = None
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        back_button(2)
        return
    eff = res.effects
    conf = eff[eff["confirmatory"]]
    cols = st.columns(5)
    cols[0].metric("Respondents", f"{len(res.data):,}")
    for c, v in zip(cols[1:], ("supported", "equivalent", "inconclusive", "opposite")):
        c.metric(v.capitalize(), int((conf["verdict"] == v).sum()))
    st.caption("Counts are confirmatory estimates. 'Equivalent' means the effect is statistically smaller than your smallest effect of interest. "
               "'Inconclusive' means the study could not tell.")
    for w in res.warnings:
        st.warning(w)
    t1, t2, t3, t4, t5 = st.tabs(["Results", "Design checks", "Robustness", "Follow-up", "Sample"])
    with t1:
        fb = FIG.forest(eff)
        if fb:
            st.image(fb, width="stretch")
        view = eff[["analysis_id", "contrast", "n", "es_metric", "es", "es_ci_low", "es_ci_high", "p_test", "p_adj", "verdict", "tag"]].copy()
        view["effect size [95% CI]"] = [REP.effect_cell(r) for r in eff.to_dict("records")]
        st.dataframe(view[["analysis_id", "contrast", "effect size [95% CI]", "p_test", "p_adj", "verdict"]],
                     hide_index=True, width="stretch",
                     column_config={"p_test": st.column_config.NumberColumn("p (test)", format="%.3f"),
                                    "p_adj": st.column_config.NumberColumn("p (adjusted)", format="%.3f")})
        for r in eff.to_dict("records"):
            with st.expander(f"{r['analysis_id']} · {r['verdict']}"):
                st.markdown(verdict_chip(r["verdict"]) + chip(REP.TAG_TEXT.get(r["tag"], r["tag"]), "grey"), unsafe_allow_html=True)
                st.markdown(REP.result_line(r, p).replace("<!-- su:author -->", "").replace("<!-- su:/author -->", ""))
    with t2:
        st.markdown(f"**Sample-ratio check:** chi-square {res.srm['chi2']}, p {REP.fp(res.srm['p'])}" if res.srm.get("p") is not None else "Not applicable.")
        if len(res.balance):
            st.dataframe(res.balance, hide_index=True, width="stretch")
        if len(res.attrition):
            st.dataframe(res.attrition.assign(missing_by_arm=res.attrition["missing_by_arm"].map(str)), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame([{"outcome": k, **v} for k, v in res.outcome_info.items()]), hide_index=True, width="stretch")
    with t3:
        if len(res.spec_summary):
            sb = FIG.spec_curves(res.spec, p.alpha)
            if sb:
                st.image(sb, width="stretch")
            st.dataframe(res.spec_summary, hide_index=True, width="stretch")
        else:
            st.info("No specification curves for this plan.")
    with t4:
        st.dataframe(res.followups, hide_index=True, width="stretch") if len(res.followups) else st.info("Nothing to plan.")
    with t5:
        st.dataframe(pd.DataFrame(res.flow), hide_index=True, width="stretch")
    c1, c2, c3 = st.columns([1, 2, 5])
    with c1:
        back_button(2)
    with c2:
        if st.button("Re-run", key="rerun"):
            s["result"] = None
            st.rerun()
    with c3:
        next_button("Continue to the report →", 4, key="to_report")
        if s["package"] is None:
            pass


# ------------------------------------------------------------------ step 5: report
def _build(s: dict) -> None:
    k = s.get("k_stats_ok", True)
    s["generated_on"] = s["generated_on"] or dt.date.today().isoformat()
    s["package"] = build_package(s["result"], lock=s["lock"], priv=s.get("priv_summary"), include_data=s["include_data"], df_input=s["clean"],
                                 repo_url=f"https://github.com/{default_repo()}", generated_on=s["generated_on"], narrative=s["narrative"])


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def step_report() -> None:
    s = S()
    res = s["result"]
    ks = (s.get("priv_summary") or {}).get("k_stats") or {}
    data_blocked = bool(ks) and ks.get("min_k") is not None and ks["min_k"] < ks.get("k_target", 0)
    st.subheader("What goes into the package")
    s["include_data"] = st.toggle("Include the de-identified data so others can re-run the analysis", s["include_data"] and not data_blocked,
                                  disabled=data_blocked, key="su_incl",
                                  help="Without data the package still contains the plan, code-free results, hashes and the report.")
    if data_blocked:
        st.warning("Some combinations of your quasi-identifiers are below k, so respondent-level data cannot be included. Go back and generalise.")
    llm_settings("narr")
    cfg = _llm_cfg()
    if cfg.provider != "none":
        if st.button("Write the summary with AI (numbers are filled in and checked)", key="narr"):
            try:
                s["narrative"] = LLM.draft_narrative(res, LLM.LLM(cfg))
                s["package"] = None
            except (LLM.NarrativeRejected, LLM.BudgetExceeded, RuntimeError, ValueError) as e:
                st.error(f"Draft rejected: {e}. The automatic summary is used instead.")
    if s["narrative"] and st.button("Go back to the automatic summary", key="narr_off"):
        s["narrative"] = None
        s["package"] = None
        st.rerun()
    if s["package"] is None or s["package"].files.get("plan.json") is None:
        _build(s)
    pkg = s["package"]
    v = pkg.verification
    if bool(pkg.files.get("data/analysis_input.csv")) != s["include_data"]:
        _build(s)
        pkg = s["package"]
        v = pkg.verification
    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.markdown(chip("numbers verified" if v["ok"] else "VERIFICATION FAILED", "ok" if v["ok"] else "bad"), unsafe_allow_html=True)
    c1.caption(f"{v['numbers_checked']} numbers checked · {len(v['unmatched'])} unmatched · {v['estimates_reported']} of {v['estimates_total']} estimates reported")
    c2.markdown(chip("privacy gate clean" if not pkg.gate else "PRIVACY GATE BLOCKED", "ok" if not pkg.gate else "bad"), unsafe_allow_html=True)
    c2.caption("Every file re-scanned for identifiers" if not pkg.gate else f"{len(pkg.gate)} problem(s)")
    timing = res.timing["status"]
    c3.markdown(chip({"before_data": "plan locked before data", "after_data": "plan locked AFTER data", "no_lock": "plan not locked",
                      "no_data_date": "plan locked", "tampered": "LOCK EDITED"}[timing],
                     {"before_data": "ok", "no_data_date": "info"}.get(timing, "warn")), unsafe_allow_html=True)
    c3.caption(res.timing["text"][:120])
    tabs = st.tabs(["Report", "Files", "Verification detail"])
    with tabs[0]:
        render_report(pkg.files["report.md"].decode(), lambda path: pkg.files.get(path))
    with tabs[1]:
        st.dataframe(pd.DataFrame([{"file": k, "bytes": len(b)} for k, b in sorted(pkg.files.items())]), hide_index=True, width="stretch")
    with tabs[2]:
        if v["ok"]:
            st.success("Every number in the text is backed by a result table, every row carries its own numbers, and no estimate is left out.")
        for u in v["unmatched"][:30]:
            st.markdown(f"- line {u['line']} ({u['section']}): **{u['number']}** · {u['context']}")
        for m in v["row_mismatches"][:30]:
            st.markdown(f"- {m['analysis_id']} {m['field']}: printed {m['printed']}, table says {m['actual']}")
        if v["estimates_missing"]:
            st.markdown("- Not reported: " + ", ".join(v["estimates_missing"]))
        for g in pkg.gate:
            st.markdown(f"- Privacy gate · `{g.path}`: {g.problem}")
        st.caption("Text the authors wrote (title, labels, reasons, description) is shown unchanged and is not checked.")
    c1, c2, c3 = st.columns([1, 2, 3])
    with c1:
        back_button(3)
    with c2:
        st.download_button("Download the package (.zip)", _zip(pkg.files), f"{pkg.slug}.zip", "application/zip", key="dl_zip")
    with c3:
        next_button("Continue to publish →", 5, disabled=not pkg.ready, key="to_publish")
        if not pkg.ready:
            st.caption("The package must pass both checks before it can be published.")


# ------------------------------------------------------------------ step 6: publish
def step_publish() -> None:
    s = S()
    pkg = s["package"]
    p: Plan = s["plan"]
    if not pkg.ready:
        st.error("This package did not pass its checks. Go back to the report.")
        back_button(4)
        return
    st.markdown('<div class="su-step-note">Publishing is your decision. Nothing leaves this session until you press a button below.</div>',
                unsafe_allow_html=True)
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("#### Save a copy")
        st.download_button("Download the package (.zip)", _zip(pkg.files), f"{pkg.slug}.zip", "application/zip", key="dl_zip2", width="stretch")
        if not is_hosted():
            if st.button("Save into this app's studies/ folder", key="save_local", width="stretch"):
                base = write_package(pkg, studies_dir())
                st.success(f"Saved to {base}")
        else:
            st.caption("A hosted app cannot keep files. Download, or commit to GitHub.")
    with c2:
        st.markdown("#### Commit to your GitHub repository")
        repo = st.text_input("Repository", default_repo(), key="su_repo", help="owner/name. The package goes to studies/<folder name>/.")
        branch = st.text_input("Branch", "main", key="su_branch")
        token = secret("GITHUB_TOKEN")
        if token:
            st.caption("Using the GITHUB_TOKEN secret.")
        else:
            token = st.text_input("GitHub token (fine-grained, contents: write, this repository only)", type="password", key="su_ghtoken")
        public = st.checkbox("I understand that if this repository is public, everything in the package becomes public.", key="su_public_ok")
        if st.button("Commit to GitHub", type="primary", disabled=not (token and public), key="do_publish", width="stretch"):
            try:
                out = publish_files(pkg.files, repo=repo, token=token, subdir=f"studies/{p.slug}", branch=branch,
                                    message=f"Add study: {p.title}")
                s["published"] = out
            except GitHubError as e:
                st.error(str(e))
    if s["published"]:
        o = s["published"]
        st.success(f"Committed {o['n_files']} files in one commit.")
        st.markdown(f"[View the study folder]({o['html_url']}) · [View the commit]({o['commit_url']})")
        st.caption("If the Streamlit app is deployed from this repository, it redeploys automatically and the study appears in the Library.")
    with st.expander("List this study in someone else's library (registry entry)"):
        st.code(json.dumps({"repo": repo if 'repo' in dir() else default_repo(), "path": f"studies/{p.slug}", "ref": "main"}, indent=1), language="json")
    c1, c2 = st.columns([1, 6])
    with c1:
        back_button(4)
    with c2:
        st.button("Start another study", on_click=reset, key="restart")


# ------------------------------------------------------------------ page
def page() -> None:
    inject_css()
    s = S()
    st.title("New study")
    nav()
    st.progress((s["step"] + 1) / len(STEPS))
    {0: step_data, 1: step_privacy, 2: step_plan, 3: step_analyze, 4: step_report, 5: step_publish}[s["step"]]()
