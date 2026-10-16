"""Assemble a study package (a dict of path -> bytes), verify it, gate it, hash it."""
from __future__ import annotations

import hashlib
import io
import json
import platform
from dataclasses import dataclass, field
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
import scipy
import statsmodels

from . import __version__
from . import figures as FIG
from . import privacy as PRIV
from . import report as REP
from . import verify as VER
from .analyze import AnalysisResult
from .credits import LICENSE_CONTENT, ORIGINATOR, ORIGINATOR_PROJECT, ORIGINATOR_REPO, TOOL_NAME
from .schema import plan_to_dict

MANIFEST = "MANIFEST.json"


def environment() -> dict:
    return {"pandas": pd.__version__, "numpy": np.__version__, "scipy": scipy.__version__,
            "statsmodels": statsmodels.__version__, "matplotlib": matplotlib.__version__, "scienceunbound": __version__}


@dataclass
class Package:
    files: dict[str, bytes]
    verification: dict
    gate: list[PRIV.GateIssue]
    slug: str
    warnings: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.verification.get("ok")) and not self.gate


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _json(obj: Any) -> bytes:
    return (json.dumps(obj, indent=1, ensure_ascii=False, default=_default) + "\n").encode("utf-8")


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def tables_for_verification(res: AnalysisResult, priv_numbers: list[float]) -> dict:
    return {"spec_summary": res.spec_summary, "balance": res.balance, "attrition": res.attrition, "srm": res.srm,
            "followups": res.followups, "flow": res.flow, "outcome_info": res.outcome_info, "priv": priv_numbers,
            "warnings": res.warnings}


def _cff(plan, generated_on: str, repo_url: str) -> bytes:
    lines = ["cff-version: 1.2.0", "message: \"If you use this report or its data, please cite it as below.\"",
             f"title: {json.dumps(plan.title)}", "type: dataset", "authors:"]
    for a in (plan.authors or ["Unknown"]):
        lines.append(f"  - name: {json.dumps(a)}")
    lines += [f"date-released: {generated_on}", f"license: {LICENSE_CONTENT.replace(' ', '-')}"]
    if repo_url:
        lines.append(f"repository-code: {json.dumps(repo_url)}")
    lines += ["references:", "  - type: software", f"    title: {json.dumps(TOOL_NAME)}", f"    version: {json.dumps(__version__)}",
              "  - type: generic", f"    title: {json.dumps('Filedrawer.org: automated research reports for unpublished studies (idea and first implementation)')}",
              "    authors:", f"      - name: {json.dumps(ORIGINATOR)}", f"    url: {json.dumps(ORIGINATOR_REPO)}"]
    return ("\n".join(lines) + "\n").encode()


REPRODUCE_SCRIPT = '''"""Re-run this study and check every number.

    pip install "scienceunbound @ git+https://github.com/{repo}"
    python scripts/reproduce.py

Checks: file hashes against MANIFEST.json, the input data hash, every estimate against results/effects.csv, and every
number in report.md against the recomputed tables.
"""
import pathlib
import sys

from scienceunbound.reproduce import reproduce

out = reproduce(pathlib.Path(__file__).resolve().parents[1])
print(out["summary"])
sys.exit(0 if out["ok"] else 1)
'''


def priv_numbers_of(priv: dict) -> list[float]:
    """Every number the privacy step may legitimately put in the report: counts, k statistics, and counts inside the actions taken."""
    import re
    k_stats = priv.get("k_stats") or {}
    nums = [float(len(priv.get("dropped") or [])), float(len(priv.get("kept") or {}))]
    nums += [float(v) for v in k_stats.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    for a in priv.get("k_actions") or []:
        nums += [float(m) for m in re.findall(r"(?<![\w.])\d+(?![\w.])", a)]
    return nums


def build_package(res: AnalysisResult, *, lock: dict | None, priv: dict | None, include_data: bool, df_input: pd.DataFrame | None,
                  repo_url: str, generated_on: str, narrative: dict | None = None) -> Package:
    plan = res.plan
    priv = priv or {}
    env = environment()
    figs: dict[str, bytes] = {}
    fb = FIG.forest(res.effects) if not res.effects.empty else None
    if fb:
        figs["figures/forest.png"] = fb
    sb = FIG.spec_curves(res.spec, plan.alpha)
    if sb:
        figs["figures/spec_curves.png"] = sb
    md = REP.build_report(res, lock=lock, priv=priv, include_data=include_data, repo_url=repo_url, generated_on=generated_on,
                          figures={"forest": bool(fb), "spec": bool(sb)}, narrative=narrative, env=env)
    k_stats = priv.get("k_stats") or {}
    priv_numbers = priv_numbers_of(priv)
    v = VER.verify_report(md, res.effects, tables_for_verification(res, priv_numbers), plan_to_dict(plan), extras=priv_numbers)
    md = md.replace("{VERIFICATION}", VER.verification_block(v))
    files: dict[str, bytes] = {"report.md": md.encode("utf-8"), **figs}
    files["plan.json"] = _json(plan_to_dict(plan))
    if lock:
        files["plan.lock.json"] = _json(lock)
    eff = res.effects
    files["results/effects.csv"] = _csv(eff)
    files["results/spec_curve.csv"] = _csv(res.spec)
    files["results/spec_summary.csv"] = _csv(res.spec_summary)
    files["results/balance.csv"] = _csv(res.balance)
    files["results/attrition.csv"] = _csv(res.attrition.assign(missing_by_arm=res.attrition["missing_by_arm"].map(json.dumps))
                                          if len(res.attrition) else res.attrition)
    files["results/followups.csv"] = _csv(res.followups)
    files["results/diagnostics.json"] = _json({"srm": res.srm, "flow": res.flow, "outcome_info": res.outcome_info,
                                                "warnings": res.warnings, "tags": res.tags, "timing": res.timing,
                                                "registered_not_run": res.registered_not_run})
    if include_data and df_input is not None:
        files["data/analysis_input.csv"] = _csv(df_input)
    conf = eff[eff["confirmatory"].astype(bool)] if len(eff) else eff
    study = {
        "schema": "scienceunbound.study/1", "slug": plan.slug, "title": plan.title, "authors": plan.authors,
        "summary": plan.summary, "created": generated_on, "tool": {"name": TOOL_NAME, "version": __version__},
        "design": plan.design, "n_analysis": int(len(res.data)), "constructs": sorted({h.construct for h in plan.hypotheses if h.construct}),
        "estimates": [{k: (None if (isinstance(x, float) and not np.isfinite(x)) else x) for k, x in r.items() if k in (
            "analysis_id", "hypothesis", "label", "construct", "confirmatory", "outcome", "contrast", "n", "es_metric", "es",
            "es_se", "es_ci_low", "es_ci_high", "p", "p_adj", "verdict", "tag")} for r in eff.to_dict("records")],
        "verdicts": {k: int(x) for k, x in conf["verdict"].value_counts().items()} if len(conf) else {},
        "plan_sha256": res.plan_sha256, "data_sha256": res.data_sha256, "data_included": bool(include_data),
        "lock": ({"sha256": lock["sha256"], "locked_at": lock["locked_at"], "anchor": lock.get("anchor")} if lock else None),
        "timing_status": res.timing["status"], "timing_text": res.timing["text"],
        "verification": {"ok": v["ok"], "numbers_checked": v["numbers_checked"], "unmatched": len(v["unmatched"]),
                         "row_mismatches": len(v["row_mismatches"]), "estimates_total": v["estimates_total"],
                         "estimates_reported": v["estimates_reported"]},
        "privacy": {"columns_removed": len(priv.get("dropped") or []), "k_target": k_stats.get("k_target"), "min_k": k_stats.get("min_k"),
                    "numbers": priv_numbers},
        "license": LICENSE_CONTENT, "repo": repo_url, "environment": env,
        "credits": {"idea": f"{ORIGINATOR}, {ORIGINATOR_PROJECT}", "url": ORIGINATOR_REPO},
    }
    files["study.json"] = _json(study)
    files["CITATION.cff"] = _cff(plan, generated_on, repo_url)
    files["scripts/reproduce.py"] = REPRODUCE_SCRIPT.format(repo=(repo_url.split("github.com/")[-1] if "github.com/" in repo_url else "OWNER/ScienceUnbound")).encode()
    gate = PRIV.gate_files(files, allow_data=include_data)
    files[MANIFEST] = _json({"schema": "scienceunbound.manifest/1", "files": {p: hashlib.sha256(b).hexdigest() for p, b in sorted(files.items())}})
    return Package(files=files, verification=v, gate=gate, slug=plan.slug, warnings=list(res.warnings))


def write_package(pkg: Package, root, subdir: str | None = None):
    from pathlib import Path
    base = Path(root) / (subdir if subdir is not None else pkg.slug)
    for rel, blob in pkg.files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob)
    return base
