import copy

from scienceunbound import registration as REG
from scienceunbound.schema import plan_from_dict, plan_to_dict


def tags(plan, lock):
    t, missing = REG.tag_hypotheses(plan, lock)
    return {x["id"]: x for x in t}, missing


def test_unchanged_plan_is_registered_and_exploratory_is_labelled(demo_plan, demo_lock):
    t, missing = tags(demo_plan, demo_lock)
    assert t["H1"]["tag"] == "registered" and t["H3"]["tag"] == "registered" and t["E1"]["tag"] == "exploratory"
    assert not missing


def test_changing_a_covariate_is_a_deviation_and_names_the_field(demo_plan, demo_lock):
    p = plan_from_dict(plan_to_dict(demo_plan))
    p.hypotheses[0].covariates = ["party", "age"]
    t, _ = tags(p, demo_lock)
    assert t["H1"]["tag"] == "deviation" and any("covariates" in d for d in t["H1"]["differences"])
    assert t["H2"]["tag"] == "registered"


def test_changing_an_outcome_definition_or_exclusion_deviates_every_dependent_test(demo_plan, demo_lock):
    p = plan_from_dict(plan_to_dict(demo_plan))
    p.outcomes[0].items = p.outcomes[0].items[:3]
    t, _ = tags(p, demo_lock)
    assert t["H1"]["tag"] == "deviation" and any(d.startswith("outcome:") for d in t["H1"]["differences"])
    p2 = plan_from_dict(plan_to_dict(demo_plan))
    p2.exclusions = p2.exclusions[:1]
    t2, _ = tags(p2, demo_lock)
    assert all(t2[h]["tag"] == "deviation" for h in ("H1", "H2", "H3"))


def test_cosmetic_edits_do_not_create_deviations(demo_plan, demo_lock):
    p = plan_from_dict(plan_to_dict(demo_plan))
    p.title, p.summary, p.authors = "New title", "New words", ["Someone Else"]
    t, _ = tags(p, demo_lock)
    assert t["H1"]["tag"] == "registered"


def test_a_hypothesis_added_after_the_lock_is_unregistered_and_a_dropped_one_is_reported(demo_plan, demo_lock):
    p = plan_from_dict(plan_to_dict(demo_plan))
    new = copy.deepcopy(p.hypotheses[0])
    new.id = "H9"
    p.hypotheses = [h for h in p.hypotheses if h.id != "H2"] + [new]
    t, missing = tags(p, demo_lock)
    assert t["H9"]["tag"] == "unregistered" and missing == ["H2"]


def test_no_lock_means_unlocked_not_registered(demo_plan):
    t, _ = tags(demo_plan, None)
    assert t["H1"]["tag"] == "unlocked"


def test_a_hand_edited_lock_is_detected(demo_lock):
    bad = copy.deepcopy(demo_lock)
    bad["plan"]["alpha"] = 0.10
    assert REG.lock_is_intact(demo_lock) and not REG.lock_is_intact(bad)


def test_timing_statuses(demo_plan, demo_lock):
    assert REG.timing_status(demo_plan, None)["status"] == "no_lock"
    assert REG.timing_status(demo_plan, demo_lock)["status"] == "before_data"
    late = REG.make_lock(demo_plan, when="2026-06-01T00:00:00Z")
    assert REG.timing_status(demo_plan, late)["status"] == "after_data"
    p = plan_from_dict(plan_to_dict(demo_plan))
    p.data_collected_through = ""
    assert REG.timing_status(p, demo_lock)["status"] == "no_data_date"
    bad = copy.deepcopy(demo_lock)
    bad["plan"]["alpha"] = 0.2
    assert REG.timing_status(demo_plan, bad)["status"] == "tampered"
    anchored = copy.deepcopy(demo_lock)
    anchored["anchor"] = {"commit": "a" * 40, "committed_at": "2026-03-01T10:05:00Z"}
    t = REG.timing_status(demo_plan, anchored)
    assert t["anchored"] and "committed to GitHub" in t["text"] and "self-asserted" not in t["text"]


def test_a_lock_written_before_a_new_plan_field_existed_still_reads_as_registered(demo_plan):
    """Regression: adding `weights` to Hypothesis must not turn every old lock into a wall of deviations."""
    lock = REG.make_lock(demo_plan, when="2026-03-01T10:00:00Z")
    for h in lock["plan"]["hypotheses"]:
        h.pop("weights", None)
    import hashlib
    from scienceunbound.schema import plan_hash
    lock["sha256"] = plan_hash(lock["plan"])                     # an old lock is internally consistent
    assert REG.lock_is_intact(lock)
    t, _ = REG.tag_hypotheses(demo_plan, lock)
    assert {x["id"]: x["tag"] for x in t} == {"H1": "registered", "H2": "registered", "H3": "registered", "E1": "exploratory"}
