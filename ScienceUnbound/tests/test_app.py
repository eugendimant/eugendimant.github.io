"""Drive the real Streamlit pages headlessly (AppTest). A real browser pass is done separately."""
import os
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

SRC = str(Path(__file__).resolve().parents[1] / "src")
HEAD = f"import sys\nsys.path.insert(0, {SRC!r})\nimport streamlit as st\n"


def page(mod: str, extra: str = "") -> AppTest:
    return AppTest.from_string(HEAD + extra + f"from scienceunbound.ui import {mod}\n{mod}.page()\n", default_timeout=180)


def ok(at):
    assert not at.exception, [e.value for e in at.exception]


@pytest.fixture()
def studies(tmp_path, monkeypatch, demo_package):
    from scienceunbound.package import write_package
    write_package(demo_package, tmp_path / "studies")
    monkeypatch.setenv("SU_STUDIES_DIR", str(tmp_path / "studies"))
    return tmp_path / "studies"


def test_static_pages_render_without_error(studies):
    for mod in ("home", "about", "library", "meta"):
        at = page(mod, "st.session_state['su_pages'] = {}\n").run()
        ok(at)


def test_about_page_credits_the_originator_and_lists_ten_improvements():
    at = page("about").run()
    ok(at)
    text = " ".join(m.value for m in at.markdown)
    assert "Yamil Ricardo Velez" in text and "Filedrawer.org" in text
    assert len(at.dataframe[0].value) == 10


def test_library_lists_and_opens_a_study(studies):
    at = page("library").run()
    ok(at)
    assert "Does an informational message raise trust" in " ".join(m.value for m in at.markdown)
    at.button(key="open_demo-info-trust").click().run()
    ok(at)
    assert any("Numbers verified: PASSED" in m.value for m in at.markdown)


def test_meta_page_handles_a_single_study(studies):
    at = page("meta").run()
    ok(at)
    assert any("at least two" in i.value for i in at.info)


def test_full_workflow_demo_to_publish():
    at = page("workbench").run()
    ok(at)
    # 1 data
    at.button(key="demo").click().run(); ok(at)
    at.button(key="to_privacy").click().run(); ok(at)
    # 2 privacy: planted identifiers are flagged, quasi-identifier risk is shown, generalise, continue
    assert dict((m.label, m.value) for m in at.metric)["Columns flagged"] == "7"
    at.button(key="gen_k").click().run(); ok(at)
    assert any("Generalisation applied" in m.value for m in at.markdown)
    at.button(key="to_plan").click().run(); ok(at)
    # 3 plan: the demo plan is valid, lock it, continue
    at.button(key="do_lock").click().run(); ok(at)
    assert any("locked" in m.value for m in at.markdown)
    at.button(key="to_analyze").click().run(); ok(at)
    # 4 analyze
    at.button(key="run").click().run(); ok(at)
    m = dict((x.label, x.value) for x in at.metric)
    assert m["Respondents"] and m["Supported"] == "1"
    assert sum(int(m[k]) for k in ("Supported", "Equivalent", "Inconclusive", "Opposite")) == 6
    at.button(key="to_report").click().run(); ok(at)
    # 5 report: verification and privacy gate pass
    body = " ".join(x.value for x in at.markdown)
    assert "numbers verified" in body and "privacy gate clean" in body
    assert not [b for b in at.button if b.key == "to_publish" and b.disabled]
    at.button(key="to_publish").click().run(); ok(at)
    assert any("Commit to your GitHub repository" in x.value for x in at.markdown)


def test_continue_is_blocked_until_the_plan_is_valid():
    at = page("workbench").run()
    at.button(key="demo").click().run()
    at.button(key="to_privacy").click().run()
    at.button(key="to_plan").click().run()
    ok(at)
    from scienceunbound.schema import Plan
    at.session_state["su"]["plan"] = Plan()
    at.run(); ok(at)
    assert [b for b in at.button if b.key == "to_analyze"][0].disabled
    assert any("To continue, fix" in e.value for e in at.error)


def test_keeping_a_flagged_column_requires_a_reason():
    at = page("workbench").run()
    at.button(key="demo").click().run()
    at.button(key="to_privacy").click().run()
    s = at.session_state["su"]
    s["drop"] = [c for c in s["drop"] if c != "RecipientEmail"]
    at.run(); ok(at)
    assert [b for b in at.button if b.key == "to_plan"][0].disabled
    assert any("Give a reason" in c.value for c in at.caption)


def test_hosted_mode_warns_about_uploads(monkeypatch):
    monkeypatch.setenv("SU_MODE", "hosted")
    at = page("workbench").run()
    ok(at)
    assert any("Hosted app" in w.value for w in at.warning)
    monkeypatch.setenv("SU_MODE", "local")
    at2 = page("workbench").run()
    assert any("Running on your computer" in s.value for s in at2.success)


def test_report_view_hides_verifier_markers(demo_package):
    at = AppTest.from_string(HEAD + "from scienceunbound.ui.common import render_report\n"
                             "render_report(" + repr(demo_package.files["report.md"].decode()) + ", lambda p: None)\n").run()
    ok(at)
    assert not any("<!--" in m.value for m in at.markdown)
    assert any("Numbers verified: PASSED" in m.value for m in at.markdown)
