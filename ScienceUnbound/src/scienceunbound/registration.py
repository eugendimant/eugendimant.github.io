"""Plan locking and deterministic deviation tagging.

A lock is a SHA-256 of the canonical plan plus a snapshot of the plan. When analyses run, every hypothesis is compared with
the snapshot field by field (no model reads the plan). A lock stamped by this tool is a self-asserted timestamp until it is
committed to a service that stamps commits independently, such as GitHub; `anchor` records that commit when it exists.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from .schema import Plan, canonical_json, plan_from_dict, plan_hash, plan_to_dict

LOCK_VERSION = "1"
# plan-level fields that change what a hypothesis means; everything else (title, summary, authors, URLs) is ignorable
RELEVANT_PLAN_FIELDS = ("design", "arm_column", "control_level", "alpha", "multiplicity", "exclusions")


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_lock(plan: Plan, when: str | None = None, note: str = "") -> dict:
    d = plan_to_dict(plan)
    return {"lock_version": LOCK_VERSION, "sha256": plan_hash(d), "locked_at": when or utcnow(), "note": note,
            "plan": d, "anchor": None}


def lock_is_intact(lock: dict) -> bool:
    """The stored snapshot still hashes to the stored digest (the lock file was not edited by hand)."""
    return bool(lock) and plan_hash(lock.get("plan") or {}) == lock.get("sha256")


def _flat(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        for i, v in enumerate(obj):
            out.update(_flat(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = canonical_json(obj)
    return out


def _diff(a: Any, b: Any) -> list[str]:
    fa, fb = _flat(a), _flat(b)
    return sorted(k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k))


def _hyp(plan: dict, hid: str) -> dict | None:
    return next((h for h in plan.get("hypotheses", []) if h.get("id") == hid), None)


def _outcome(plan: dict, name: str) -> dict | None:
    return next((o for o in plan.get("outcomes", []) if o.get("name") == name), None)


def tag_hypotheses(plan: Plan, lock: dict | None) -> tuple[list[dict], list[str]]:
    """Return ([{id, tag, differences, reason}], [registered ids that the current plan no longer contains]).

    tags: registered | deviation | unregistered (added after the lock) | exploratory | unlocked (no lock exists)
    """
    cur = plan_to_dict(plan)
    out: list[dict] = []
    if not lock:
        for h in plan.hypotheses:
            out.append({"id": h.id, "tag": "unlocked" if h.confirmatory else "exploratory", "differences": [], "reason": ""})
        return out, []
    # a snapshot written by an older version lacks fields added since; fill their defaults so that is not a "difference"
    snap = plan_to_dict(plan_from_dict(lock["plan"]))
    for h in plan.hypotheses:
        if not h.confirmatory:
            out.append({"id": h.id, "tag": "exploratory", "differences": [], "reason": ""})
            continue
        old = _hyp(snap, h.id)
        if old is None or not old.get("confirmatory", True):
            out.append({"id": h.id, "tag": "unregistered", "differences": [], "reason": "not in the locked plan"})
            continue
        diffs = _diff(old, _hyp(cur, h.id))
        oo, no = _outcome(snap, old["outcome"]), _outcome(cur, h.outcome)
        diffs += [f"outcome:{d}" for d in _diff(oo, no)]
        for f in RELEVANT_PLAN_FIELDS:
            diffs += [f"plan.{d}" if d else f"plan.{f}" for d in _diff({f: snap.get(f)}, {f: cur.get(f)})]
        diffs = sorted(set(diffs))
        out.append({"id": h.id, "tag": "deviation" if diffs else "registered", "differences": diffs,
                    "reason": plan.deviation_notes.get(h.id, "") if diffs else ""})
    missing = [h["id"] for h in snap.get("hypotheses", []) if h.get("confirmatory", True)
               and h["id"] not in {x.id for x in plan.hypotheses}]
    return out, missing


def timing_status(plan: Plan, lock: dict | None) -> dict:
    """What can honestly be said about when the plan existed relative to the data."""
    if not lock:
        return {"status": "no_lock", "text": "No plan was locked. Confirmatory labels are intentions, not pre-registration."}
    if not lock_is_intact(lock):
        return {"status": "tampered", "text": "The lock file does not match its own hash: it was edited after locking."}
    when = lock["locked_at"]
    anchor = lock.get("anchor") or {}
    stamp = f"locked {when}" + (f" and committed to GitHub as `{anchor.get('commit', '')[:10]}` at {anchor.get('committed_at', '')}" if anchor else " (self-asserted time; not yet committed to GitHub)")
    end = (plan.data_collected_through or "").strip()
    if not end:
        return {"status": "no_data_date", "anchored": bool(anchor),
                "text": f"Plan {stamp}. The end of data collection was not declared, so the order of plan and data cannot be checked."}
    if when[:10] <= end:
        return {"status": "before_data", "anchored": bool(anchor),
                "text": f"Plan {stamp}, on or before the declared end of data collection ({end})."}
    return {"status": "after_data", "anchored": bool(anchor),
            "text": f"Plan {stamp}, AFTER the declared end of data collection ({end}). This is not pre-registration."}
