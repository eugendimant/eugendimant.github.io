"""Live-fire: the verifier must stay silent on the clean report and fire on every injected defect."""
import re

import pytest

from scienceunbound import llm as LLM
from scienceunbound import verify as VER
from scienceunbound.package import tables_for_verification
from scienceunbound.report import _fill
from scienceunbound.schema import plan_to_dict


@pytest.fixture(scope="module")
def md(demo_package):
    return demo_package.files["report.md"].decode()


def run(md, res):
    return VER.verify_report(md, res.effects, tables_for_verification(res, [1.0]), plan_to_dict(res.plan), extras=[1.0])


def test_clean_report_has_zero_false_positives(md, demo_result):
    v = run(md, demo_result)
    assert v["ok"], (v["unmatched"][:3], v["row_mismatches"][:3], v["estimates_missing"])
    assert v["numbers_checked"] > 150 and v["estimates_reported"] == v["estimates_total"] == len(demo_result.effects)


def edit(md, old, new, count=1):
    assert md.count(old) >= 1, old
    return md.replace(old, new, count)


def line_of(md, key):
    return next(l for l in md.splitlines() if l.startswith("- **" + key + "**"))


def test_fires_on_a_changed_effect_size_in_prose(md, demo_result):
    row = demo_result.effects.set_index("analysis_id").loc["H1:info"]
    line = line_of(md, "H1:info")
    bad = line.replace(f"g = {0.49:.2f}", "g = 0.94") if "g = 0.49" in line else None
    assert bad, line
    v = run(md.replace(line, bad), demo_result)
    assert not v["ok"] and any(m["analysis_id"] == "H1:info" for m in v["row_mismatches"])


def test_fires_on_swapped_numbers_between_two_rows(md, demo_result):
    """Both numbers exist in the tables, so only the row-bound check can see this."""
    a, b = line_of(md, "H1:info"), line_of(md, "H2:info")
    ga = re.search(r"g = (\S+ \[[^\]]+\])", a).group(1)
    gb = re.search(r"g = (\S+ \[[^\]]+\])", b).group(1)
    swapped = md.replace(a, a.replace(ga, gb)).replace(b, b.replace(gb, ga))
    v = run(swapped, demo_result)
    assert not v["ok"] and {m["analysis_id"] for m in v["row_mismatches"]} >= {"H1:info", "H2:info"}


def test_fires_on_a_changed_sample_size(md, demo_result):
    line = line_of(md, "H2:social")
    v = run(md.replace(line, re.sub(r"N = \d+", "N = 999", line)), demo_result)
    assert any(m["field"] == "N" for m in v["row_mismatches"])


def test_fires_on_a_made_up_number_in_new_prose(md, demo_result):
    v = run(md.replace("## Limitations", "## Limitations\n\nThe message improved trust by 37% in the field.", 1), demo_result)
    assert not v["ok"] and any(u["number"] == "37%" or u["number"] == "37" for u in v["unmatched"])


def test_fires_on_a_changed_table_cell(md, demo_result):
    row = next(l for l in md.splitlines() if l.startswith("| H1:social |"))
    cells = row.split("|")
    cells[7] = " .003 "                                         # the p column
    v = run(md.replace(row, "|".join(cells)), demo_result)
    assert any(m["analysis_id"] == "H1:social" for m in v["row_mismatches"])


def test_fires_when_an_inconvenient_result_is_omitted(md, demo_result):
    lines = [l for l in md.splitlines() if not (l.startswith("| H2:social |") or l.startswith("- **H2:social**"))]
    v = run("\n".join(lines), demo_result)
    assert "H2:social" in v["estimates_missing"] and not v["ok"]


def test_fires_when_p_less_than_claims_more_than_the_table_supports(md, demo_result):
    line = line_of(md, "H2:info")
    v = run(md.replace(line, re.sub(r"p = \.\d+ \(", "p < .001 (", line, count=1)), demo_result)
    assert any(m["analysis_id"] == "H2:info" for m in v["row_mismatches"])


def test_numbers_inside_the_verification_block_cannot_hide_a_claim(md, demo_result):
    """The block is excluded from scanning, so it must not be a place to smuggle in text that survives a re-check on the rest."""
    v1 = run(md, demo_result)
    smuggled = md.replace("<!-- su:verification:end -->", "<!-- su:verification:end -->\n\nThe effect was 12.5 SD.")
    assert not run(smuggled, demo_result)["ok"] and v1["ok"]


# ---- model-written narrative
def test_narrative_with_placeholders_is_filled_from_tables_and_verifies(demo_result):
    obj = {"summary": "Information raised trust (g = {{H1:info.es}}, p = {{H1:info.p}}); the social message did not ({{H1:social.es}}).",
           "limitations": ["Only {{H1:info.n}} respondents entered the first comparison."]}
    ok = LLM.validate_narrative(obj, demo_result.effects)
    filled = _fill(ok["summary"], demo_result.effects)
    assert "0.49" in filled and "{{" not in filled


@pytest.mark.parametrize("text", ["Trust rose by 0.5 SD.", "About 40% of people changed.", "In 2026 the effect was large."])
def test_narrative_with_a_literal_number_is_rejected(demo_result, text):
    with pytest.raises(LLM.NarrativeRejected):
        LLM.validate_narrative({"summary": text, "limitations": []}, demo_result.effects)


def test_narrative_with_an_unknown_placeholder_is_rejected(demo_result):
    with pytest.raises(LLM.NarrativeRejected):
        LLM.validate_narrative({"summary": "Effect {{H9:info.es}}", "limitations": []}, demo_result.effects)
    with pytest.raises(LLM.NarrativeRejected):
        LLM.validate_narrative({"summary": "Effect {{H1:info.sd_pooled_secret}}", "limitations": []}, demo_result.effects)


def test_an_edited_narrative_that_sneaks_in_a_number_after_filling_is_still_caught(demo_package, demo_result):
    md = demo_package.files["report.md"].decode().replace("## Design and sample", "Trust rose 73 points.\n\n## Design and sample", 1)
    assert not run(md, demo_result)["ok"]


# ---- measured detection rate of fabricated numbers, by where they are injected
def _fabricated(rng, n):
    out = []
    for _ in range(n):
        kind = rng.choice(["int", "one", "two", "pct"])
        if kind == "int":
            out.append(str(int(rng.integers(2, 900))))
        elif kind == "one":
            out.append(f"{rng.uniform(1, 60):.1f}")
        elif kind == "two":
            out.append(f"{rng.uniform(0.05, 1.5):.2f}")
        else:
            out.append(f"{int(rng.integers(6, 94))}%")
    return out


@pytest.mark.parametrize("section,min_rate", [("## Limitations", 0.95), ("## Privacy and data", 0.95), ("## Design checks", 0.85),
                                                ("## Provenance and reproducibility", 0.95)])
def test_fabricated_numbers_are_detected_at_a_measured_rate(md, demo_result, section, min_rate):
    import numpy as np
    rng = np.random.default_rng(42)
    nums = _fabricated(rng, 300)
    caught = 0
    for tok in nums:
        text = md.replace(section, f"{section}\n\nThe reported change was {tok}.", 1)
        v = run(text, demo_result)
        caught += (not v["ok"])
    assert caught / len(nums) >= min_rate, (section, caught / len(nums))


def test_a_fabricated_number_on_a_result_line_is_caught_unless_it_is_that_rows_own_number(md, demo_result):
    import numpy as np
    rng = np.random.default_rng(7)
    line = line_of(md, "H1:social")
    caught = 0
    for tok in _fabricated(rng, 200):
        v = run(md.replace(line, line + f" Trust moved by {tok}."), demo_result)
        caught += (not v["ok"])
    assert caught / 200 >= 0.9


def test_author_written_text_is_not_treated_as_a_pipeline_claim(demo_result, demo_lock, demo_clean):
    from scienceunbound.package import build_package
    from scienceunbound.schema import plan_from_dict, plan_to_dict
    p = plan_from_dict(plan_to_dict(demo_result.plan))
    p.title = "Study 2 of 3: trust in 12 cities"
    p.summary = "We recruited 4,321 people in 2025."
    p.arm_labels = {"control": "Arm 1 (control)", "info": "Arm 2", "social": "Arm 3"}
    from scienceunbound.analyze import run_analysis
    res = run_analysis(demo_clean, p, None)
    pkg = build_package(res, lock=None, priv={"dropped": []}, include_data=False, df_input=demo_clean, repo_url="", generated_on="2026-10-16")
    assert pkg.verification["ok"], pkg.verification["unmatched"][:3]
    assert "4,321" in pkg.files["report.md"].decode()           # the author's sentence is shown unchanged
