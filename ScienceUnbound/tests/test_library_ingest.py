import json

import httpx
import pandas as pd
import pytest

from scienceunbound import library as LIB
from scienceunbound.ingest import infer_dictionary, normalize, read_table
from scienceunbound.package import write_package


def test_qualtrics_three_row_header_is_removed_and_labels_kept(tmp_path):
    p = tmp_path / "q.csv"
    p.write_text('StartDate,Q1,Q2\n"Start Date","How much do you trust X?","Age"\n\'{"ImportId":"startDate"}\',\'{"ImportId":"QID1"}\',\'{"ImportId":"QID2"}\'\n2026-01-01 10:00:00,5,31\n2026-01-01 10:05:00,3,45\n')
    df, meta = read_table(p)
    assert meta["qualtrics"] and len(df) == 2 and meta["labels"]["Q1"].startswith("How much")
    assert df["Q1"].tolist() == [5, 3] and pd.api.types.is_numeric_dtype(df["Q2"])


def test_plain_csv_numeric_coercion_and_blank_handling(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("id,score,group\n1,3.5,a\n2,,b\n3,4,\n4,6.25,a\n")
    df, meta = read_table(p)
    assert not meta["qualtrics"] and df["score"].isna().sum() == 1 and df["group"].isna().sum() == 1
    d = infer_dictionary(df)
    assert d.set_index("column").loc["score", "kind"] == "numeric" and d.set_index("column").loc["group", "kind"] == "categorical"
    assert len(meta["sha256"]) == 64


def test_stata_roundtrip_and_unsupported_types(tmp_path):
    p = tmp_path / "x.dta"
    pd.DataFrame({"a": [1, 2, 3], "b": [0.5, 1.5, 2.5]}).to_stata(p, write_index=False)
    df, _ = read_table(p)
    assert df["a"].tolist() == [1, 2, 3]
    with pytest.raises(ValueError):
        read_table(tmp_path / "x.pdf") if (tmp_path / "x.pdf").write_bytes(b"%PDF") else None


def test_duplicate_columns_are_rejected(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("a,a\n1,2\n")
    with pytest.raises(ValueError):
        read_table(p)


def test_normalize_makes_dtypes_match_a_reread():
    df = pd.DataFrame({"zip": ["19104", "19103"], "g": ["a", "b"]})
    assert pd.api.types.is_numeric_dtype(normalize(df)["zip"])


def test_library_scans_local_packages_and_finds_similar_ones(demo_package, tmp_path):
    write_package(demo_package, tmp_path, "study-a")
    other = json.loads(demo_package.files["study.json"]); other["slug"] = "study-b"; other["constructs"] = ["institutional trust"]
    (tmp_path / "study-b").mkdir()
    (tmp_path / "study-b" / "study.json").write_text(json.dumps(other))
    cards = LIB.scan_local(tmp_path)
    assert {c["slug"] for c in cards} == {"demo-info-trust", "study-b"}
    a = next(c for c in cards if c["slug"] == "demo-info-trust")
    assert a["verified"] and a["n_confirmatory"] == 6
    sim = LIB.similar(a, cards)
    assert sim and sim[0][1]["slug"] == "study-b"
    eff = LIB.local_effects(tmp_path)
    assert "study" in eff.columns and len(eff) == 8


def test_remote_registry_with_a_missing_study_is_reported_not_crashed(demo_package):
    study = demo_package.files["study.json"]
    eff = demo_package.files["results/effects.csv"]

    def h(req):
        u = str(req.url)
        if "good/repo" in u and u.endswith("study.json"):
            return httpx.Response(200, content=study)
        if "good/repo" in u and u.endswith("effects.csv"):
            return httpx.Response(200, content=eff)
        return httpx.Response(404)
    LIB._CACHE.clear()
    client = httpx.Client(transport=httpx.MockTransport(h))
    cards, frame, broken = LIB.remote_cards([{"repo": "good/repo", "path": "studies/x"}, {"repo": "gone/repo", "path": "studies/y"}], client)
    assert len(cards) == 1 and broken == ["gone/repo/studies/y"] and len(frame) == 8
    assert cards[0]["where"].startswith("https://github.com/good/repo/tree/main/")


def test_registry_file_parsing(tmp_path):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"studies": [{"repo": "a/b", "path": "studies/x"}, {"repo": "", "path": "y"}, {"oops": 1}]}))
    assert LIB.load_registry(p) == [{"repo": "a/b", "path": "studies/x"}]
    assert LIB.load_registry(tmp_path / "missing.json") == []
