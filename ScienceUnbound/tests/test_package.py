import json

import pytest

from scienceunbound import privacy as PRIV
from scienceunbound.analyze import run_analysis
from scienceunbound.package import build_package, write_package
from scienceunbound.reproduce import reproduce


def test_demo_package_is_verified_clean_and_complete(demo_package):
    p = demo_package
    assert p.verification["ok"] and p.gate == [] and p.ready
    for f in ("report.md", "study.json", "plan.json", "plan.lock.json", "results/effects.csv", "MANIFEST.json",
              "CITATION.cff", "scripts/reproduce.py", "figures/forest.png"):
        assert f in p.files
    md = p.files["report.md"].decode()
    assert "Yamil Ricardo Velez" in md and "Numbers verified: PASSED" in md
    assert json.loads(p.files["study.json"])["credits"]["idea"].startswith("Yamil Ricardo Velez")


def test_reproduce_passes_from_disk(demo_package, tmp_path):
    base = write_package(demo_package, tmp_path)
    out = reproduce(base)
    assert out["ok"], out["summary"]
    assert len(out["checks"]) == 4


def test_reproduce_fails_when_any_file_is_touched(demo_package, tmp_path):
    base = write_package(demo_package, tmp_path)
    p = base / "report.md"
    p.write_text(p.read_text().replace("Authors:", "Authors :"))
    out = reproduce(base)
    assert not out["ok"] and "changed: report.md" in out["summary"]


def test_reproduce_fails_when_results_and_manifest_are_both_forged(demo_package, tmp_path):
    """A forger who edits effects.csv AND rewrites the manifest is still caught by recomputation."""
    import hashlib
    base = write_package(demo_package, tmp_path)
    eff = base / "results" / "effects.csv"
    lines = eff.read_text().splitlines()
    eff.write_text(eff.read_text().replace(lines[1].split(",")[17], "9.99", 1))
    man = json.loads((base / "MANIFEST.json").read_text())
    man["files"]["results/effects.csv"] = hashlib.sha256(eff.read_bytes()).hexdigest()
    (base / "MANIFEST.json").write_text(json.dumps(man))
    out = reproduce(base)
    assert not out["ok"]
    assert [c for c in out["checks"] if "estimate" in c["check"]][0]["ok"] is False


def test_reproduce_detects_swapped_input_data(demo_package, tmp_path):
    import hashlib
    base = write_package(demo_package, tmp_path)
    d = base / "data" / "analysis_input.csv"
    d.write_text(d.read_text().replace("control", "info", 5))
    man = json.loads((base / "MANIFEST.json").read_text())
    man["files"]["data/analysis_input.csv"] = hashlib.sha256(d.read_bytes()).hexdigest()
    (base / "MANIFEST.json").write_text(json.dumps(man))
    out = reproduce(base)
    assert not out["ok"] and any("input data hash" in c["check"] and not c["ok"] for c in out["checks"])


def test_package_without_data_gets_an_integrity_only_check(demo_result, demo_lock, demo_clean, tmp_path):
    pkg = build_package(demo_result, lock=demo_lock, priv={"dropped": []}, include_data=False, df_input=demo_clean,
                        repo_url="", generated_on="2026-10-16")
    assert "data/analysis_input.csv" not in pkg.files and pkg.ready
    out = reproduce(write_package(pkg, tmp_path))
    assert out.get("partial") and out["ok"]


def test_gate_blocks_a_package_whose_data_still_contains_identifiers(demo_raw, demo_plan, demo_lock):
    """Skipping the privacy step must not be possible by accident: the final gate re-scans the bytes."""
    res = run_analysis(demo_raw, demo_plan, demo_lock)
    pkg = build_package(res, lock=demo_lock, priv={"dropped": []}, include_data=True, df_input=demo_raw, repo_url="", generated_on="2026-10-16")
    assert not pkg.ready and any("RecipientEmail" in g.problem or "ResponseId" in g.problem for g in pkg.gate)


def test_a_package_with_a_failed_verification_is_not_ready(demo_result, demo_lock, demo_clean, monkeypatch):
    from scienceunbound import report as REP
    real = REP.result_line
    monkeypatch.setattr(REP, "result_line", lambda r, plan: real(r, plan).replace("N = ", "N = 1"))
    pkg = build_package(demo_result, lock=demo_lock, priv={"dropped": []}, include_data=False, df_input=demo_clean,
                        repo_url="", generated_on="2026-10-16")
    assert not pkg.verification["ok"] and not pkg.ready
    assert "Numbers verified: FAILED" in pkg.files["report.md"].decode()


def test_report_is_deterministic(demo_result, demo_lock, demo_clean):
    a = build_package(demo_result, lock=demo_lock, priv={"dropped": []}, include_data=False, df_input=demo_clean, repo_url="", generated_on="2026-10-16")
    b = build_package(demo_result, lock=demo_lock, priv={"dropped": []}, include_data=False, df_input=demo_clean, repo_url="", generated_on="2026-10-16")
    assert a.files["report.md"] == b.files["report.md"] and a.files["results/effects.csv"] == b.files["results/effects.csv"]
