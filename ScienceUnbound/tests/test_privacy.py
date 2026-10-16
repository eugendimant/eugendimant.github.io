import csv
import importlib.util
import sys

import numpy as np
import pandas as pd

from scienceunbound import demo, privacy
from scienceunbound.ingest import read_table


def test_every_planted_identifier_is_found(demo_raw):
    found = {f.column for f in privacy.audit_dataframe(demo_raw).findings if f.action == "drop"}
    assert set(demo.PLANTED_PII) <= found


def test_optional_columns_blank_in_first_rows_are_still_caught(tmp_path):
    """The case a first-rows-only scanner misses: optional questions blank for the first respondents."""
    rows = [["q1", "contact", "notes", "age"]]
    for i in range(200):
        contact = "" if i < 6 else f"person{i}@example.com"
        notes = "" if i < 6 else "I live near the old mill and my neighbour Maria Lopez told me about this study, so I came."
        rows.append([str(i % 5), contact, notes, str(20 + i % 40)])
    p = tmp_path / "probe.csv"
    with open(p, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    df, _ = read_table(p)
    found = {f.column: f.reason for f in privacy.audit_dataframe(df).findings}
    assert "contact" in found and "email" in found["contact"]
    assert "notes" in found and "free text" in found["notes"]
    assert "q1" not in found and "age" not in found


def test_a_single_email_hidden_deep_in_a_column_is_found():
    df = pd.DataFrame({"x": ["fine"] * 999 + ["write to jane.doe@uni.edu"]})
    assert privacy.audit_dataframe(df).findings[0].reason.startswith("contains email")


def test_no_false_positives_on_a_clean_survey(demo_clean):
    keep = demo_clean.drop(columns=[c for c in ("participant_code",) if c in demo_clean.columns])
    assert privacy.audit_dataframe(keep).findings == []


def test_closed_ended_labels_are_not_flagged_as_free_text():
    df = pd.DataFrame({"choice": ["Strongly agree with the statement given above, fully and completely"] * 40 + ["Disagree"] * 10})
    assert privacy.audit_dataframe(df).findings != []
    assert privacy.audit_dataframe(df, closed={"choice"}).findings == []


def test_reports_never_contain_cell_values(demo_raw):
    rep = privacy.audit_dataframe(demo_raw)
    blob = repr(rep.as_frame().to_dict("records"))
    for v in demo_raw["RecipientEmail"].dropna().head(20):
        assert v not in blob
    assert "Maria Lopez" not in blob


def test_k_anonymity_measures_and_enforces():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"age": rng.integers(18, 90, 400), "gender": rng.choice(["F", "M", "X"], 400, p=[.48, .48, .04]),
                       "y": rng.normal(size=400)})
    before = privacy.k_anonymity(df, ["age", "gender"], 5)
    assert before["unique_rows"] > 20 and before["min_k"] == 1
    out, actions, after = privacy.enforce_k(df, ["age", "gender"], 5)
    assert after["min_k"] >= 5 and after["rows_below_k"] == 0
    assert actions and "y" in out.columns and len(out) == len(df)
    # the generalised frame, measured again from scratch, agrees
    assert privacy.k_anonymity(out, after["quasi"], 5)["min_k"] >= 5


def test_gate_blocks_identifiers_anywhere_in_a_package():
    clean = {"report.md": b"Effects were small.", "results/effects.csv": b"analysis_id,es\nH1,0.2\n"}
    assert privacy.gate_files(clean) == []
    assert privacy.gate_files({**clean, "report.md": b"contact jane@x.org for data"})
    assert privacy.gate_files({**clean, "notes.txt": b"call 215-555-0187"})
    assert privacy.gate_files({**clean, "results/effects.csv": b"analysis_id,who\nH1,a@b.co\n"})
    big = "id,v\n" + "\n".join(f"{i},{i}" for i in range(6000))
    assert privacy.gate_files({"results/huge.csv": big.encode()})


def test_gate_scans_included_data_with_the_full_audit(demo_raw):
    bad = {"data/analysis_input.csv": demo_raw.to_csv(index=False).encode()}
    assert privacy.gate_files(bad)
    assert privacy.gate_files(bad, allow_data=False)


def test_his_scanner_misses_what_this_one_catches(tmp_path):
    """Live-fire comparison against the original tool's published scan, if its source is present locally."""
    src = "/home/user/yrvelez/filedrawer/src/filedrawer/pii.py"
    import os
    if not os.path.exists(src):
        import pytest
        pytest.skip("original source not present")
    spec = importlib.util.spec_from_file_location("fd_pii", src)
    m = importlib.util.module_from_spec(spec)
    sys.modules["fd_pii"] = m
    spec.loader.exec_module(m)
    rows = [["q1", "contact", "notes"]]
    for i in range(200):
        rows.append([str(i % 5), "" if i < 6 else f"person{i}@example.com", "" if i < 6 else "My neighbour Maria Lopez told me about this study, so I came."])
    p = tmp_path / "p.csv"
    with open(p, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    theirs = set(m.scan(p).flagged)
    ours = {f.column for f in privacy.audit_dataframe(read_table(p)[0]).findings}
    assert {"contact", "notes"} <= ours
    assert not ({"contact", "notes"} & theirs)


def test_enforce_k_never_deletes_a_column_unless_asked():
    rng = np.random.default_rng(11)
    df = pd.DataFrame({"party": rng.choice(["D", "R", "I"], 300), "tiny": rng.choice(["a", "b"], 300), "age": rng.integers(18, 90, 300)})
    out, actions, stats = privacy.enforce_k(df, ["party", "tiny", "age"], 8)
    assert {"party", "tiny", "age"} <= set(out.columns) and stats["min_k"] >= 8
    assert not any("removed (could not" in a for a in actions)


def test_rare_combinations_are_suppressed_and_the_count_is_reported():
    df = pd.DataFrame({"g": ["a"] * 50 + ["b"] * 48 + ["c", "d"], "z": ["x"] * 50 + ["y"] * 48 + ["x", "y"], "v": range(100)})
    out, actions, stats = privacy.enforce_k(df, ["g", "z"], 5)
    assert stats["min_k"] >= 5 and len(out) <= 100
    assert any("suppressed" in a or "merged" in a for a in actions)
    assert "v" in out.columns


def test_too_few_suppressed_rows_are_removed_and_reported():
    df = pd.DataFrame({"g": ["a"] * 60 + ["b", "c"], "v": range(62)})
    out, actions, stats = privacy.enforce_k(df, ["g"], 5)
    assert stats["min_k"] >= 5 and len(out) < 62 and any("removed" in a or "merged" in a for a in actions)


def test_suppression_makes_values_missing_never_a_fake_category():
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"g": ["a"] * 120 + ["b"] * 120 + ["c", "d", "e"], "z": ["x"] * 123 + ["y"] * 120})
    out, actions, stats = privacy.enforce_k(df, ["g", "z"], 5)
    assert stats["min_k"] >= 5
    for c in ("g", "z"):
        assert not out[c].astype(str).str.contains("suppressed", case=False).any()
    assert any("suppressed (set to missing)" in a for a in actions) or any("merged" in a for a in actions)
