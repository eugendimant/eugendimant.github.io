"""Re-run a study package and compare. Tolerance-based (not byte-identical) so it survives library and platform changes."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import verify as VER
from .analyze import run_analysis
from .ingest import read_table
from .package import MANIFEST, tables_for_verification
from .schema import plan_from_dict, plan_to_dict

NUMERIC_TOL = 1e-6


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_manifest(root: Path) -> list[str]:
    man = json.loads((root / MANIFEST).read_text())["files"]
    bad = []
    for rel, h in man.items():
        p = root / rel
        if not p.exists():
            bad.append(f"missing: {rel}")
        elif _sha(p) != h:
            bad.append(f"changed: {rel}")
    return bad


def _blank(x) -> bool:
    return x is None or (isinstance(x, float) and x != x) or (isinstance(x, str) and x == "")


def compare_effects(new: pd.DataFrame, old: pd.DataFrame, tol: float = NUMERIC_TOL) -> list[dict]:
    diffs = []
    new, old = new.set_index("analysis_id"), old.set_index("analysis_id")
    if set(new.index) != set(old.index):
        diffs.append({"analysis_id": "*", "column": "analysis_id", "detail": f"rows differ: {sorted(set(new.index) ^ set(old.index))}"})
    for aid in sorted(set(new.index) & set(old.index)):
        for col in old.columns:
            if col not in new.columns:
                diffs.append({"analysis_id": aid, "column": col, "detail": "column missing after re-run"})
                continue
            a, b = new.loc[aid, col], old.loc[aid, col]
            if _blank(a) and _blank(b):
                continue
            if _blank(a) != _blank(b):
                diffs.append({"analysis_id": aid, "column": col, "detail": f"{a!r} vs {b!r}"})
            elif isinstance(b, (int, float, np.integer, np.floating)) and not isinstance(b, bool):
                if abs(float(a) - float(b)) > tol * (1 + abs(float(b))):
                    diffs.append({"analysis_id": aid, "column": col, "detail": f"{a} vs {b}"})
            elif str(a) != str(b):
                diffs.append({"analysis_id": aid, "column": col, "detail": f"{a!r} vs {b!r}"})
    return diffs


def reproduce(root: str | Path, tol: float = NUMERIC_TOL) -> dict:
    root = Path(root)
    out: dict = {"ok": False, "checks": []}

    def add(name: str, ok: bool, detail: str = ""):
        out["checks"].append({"check": name, "ok": ok, "detail": detail})

    bad = check_manifest(root)
    add("file hashes match MANIFEST.json", not bad, "; ".join(bad[:5]))
    study = json.loads((root / "study.json").read_text())
    data_path = root / "data" / "analysis_input.csv"
    if not data_path.exists():
        add("analysis table present", False, "data not included in this package: only file integrity was checked")
        out["summary"] = _summary(out)
        out["ok"] = all(c["ok"] for c in out["checks"][:1])
        out["partial"] = True
        return out
    add("input data hash", _sha(data_path) == study["data_sha256"], "")
    df, _ = read_table(data_path)
    plan = plan_from_dict(json.loads((root / "plan.json").read_text()))
    lock = json.loads((root / "plan.lock.json").read_text()) if (root / "plan.lock.json").exists() else None
    res = run_analysis(df, plan, lock)
    old = pd.read_csv(root / "results" / "effects.csv")
    diffs = compare_effects(res.effects, old, tol)
    add(f"every estimate reproduced within {tol:g}", not diffs, "; ".join(f"{d['analysis_id']}.{d['column']}: {d['detail']}" for d in diffs[:5]))
    md = (root / "report.md").read_text(encoding="utf-8")
    priv = study.get("privacy", {})
    extras = [float(v) for v in (priv.get("numbers") or [priv.get("columns_removed"), priv.get("k_target"), priv.get("min_k")]) if v is not None]
    # the report's privacy section quotes numbers that come from the privacy step, not from the data table
    v = VER.verify_report(md, res.effects, tables_for_verification(res, extras), plan_to_dict(plan), extras=extras)
    add("every number in report.md matches the recomputed tables", v["ok"],
        f"{len(v['unmatched'])} unmatched, {len(v['row_mismatches'])} mismatched, missing {v['estimates_missing']}")
    out["ok"] = all(c["ok"] for c in out["checks"])
    out["summary"] = _summary(out)
    return out


def _summary(out: dict) -> str:
    lines = [("PASS " if c["ok"] else "FAIL ") + c["check"] + (f"  [{c['detail']}]" if c["detail"] and not c["ok"] else "") for c in out["checks"]]
    return "\n".join(lines)
