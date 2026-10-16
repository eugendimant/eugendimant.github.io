"""Command line: the same pipeline without the web app."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from . import __version__
from . import library as LIB
from . import meta as META
from . import privacy as PRIV
from . import registration as REG
from .analyze import run_analysis
from .demo import demo_plan, make_demo
from .ingest import normalize, read_table
from .package import build_package, write_package
from .reproduce import reproduce
from .schema import plan_from_dict, plan_to_dict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scienceunbound", description="Verified, privacy-safe reports for unpublished research.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="scan every cell of a data file for identifiers and re-identification risk")
    a.add_argument("data")
    a.add_argument("--quasi", default="", help="comma-separated columns to test for k-anonymity")
    a.add_argument("-k", type=int, default=5)
    r = sub.add_parser("run", help="run a plan on data and write a study package")
    r.add_argument("--data", required=True)
    r.add_argument("--plan", required=True)
    r.add_argument("--lock", default="")
    r.add_argument("--out", default="studies")
    r.add_argument("--include-data", action="store_true")
    r.add_argument("--keep", default="", help="columns to keep although the audit flags them")
    r.add_argument("--repo-url", default="")
    l = sub.add_parser("lock", help="lock a plan (SHA-256 + snapshot) before looking at outcomes")
    l.add_argument("plan")
    l.add_argument("--out", default="plan.lock.json")
    v = sub.add_parser("reproduce", help="re-run a study package and check every number")
    v.add_argument("package")
    m = sub.add_parser("meta", help="pool confirmatory effects by construct across studies/")
    m.add_argument("--studies", default="studies")
    k = sub.add_parser("llm-check", help="test a language-model setup end to end on the demo study (Ollama, LM Studio, Anthropic, OpenAI-style)")
    k.add_argument("--provider", default="ollama", choices=["ollama", "lmstudio", "anthropic", "openai_compatible"])
    k.add_argument("--model", default="")
    k.add_argument("--base-url", default="")
    k.add_argument("--api-key", default="", help="or set SU_LLM_API_KEY")
    c = sub.add_parser("check", help="re-audit every study under studies/: privacy gate on all files, reproduction where data is included")
    c.add_argument("--studies", default="studies")
    d = sub.add_parser("demo", help="write the synthetic demo data and plan")
    d.add_argument("--out", default="demo")
    args = ap.parse_args(argv)

    if args.cmd == "demo":
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        make_demo().to_csv(out / "demo_data.csv", index=False)
        (out / "demo_plan.json").write_text(json.dumps(plan_to_dict(demo_plan()), indent=1))
        print(f"wrote {out / 'demo_data.csv'} and {out / 'demo_plan.json'}")
        return 0
    if args.cmd == "audit":
        df, _ = read_table(args.data)
        rep = PRIV.audit_dataframe(df)
        print(f"scanned {rep.cells_scanned:,} cells in {rep.n_rows:,} rows")
        for f in rep.findings:
            print(f"  [{f.action}] {f.column}: {f.reason}" + (f" ({f.hits} hits)" if f.hits else ""))
        if not rep.findings:
            print("  no identifiers found")
        if args.quasi:
            st = PRIV.k_anonymity(df.drop(columns=rep.to_drop(), errors="ignore"), [c.strip() for c in args.quasi.split(",")], args.k)
            print("re-identification:", json.dumps(st))
        return 1 if rep.to_drop() else 0
    if args.cmd == "lock":
        plan = plan_from_dict(json.loads(Path(args.plan).read_text()))
        Path(args.out).write_text(json.dumps(REG.make_lock(plan), indent=1))
        print(f"locked: {args.out}")
        return 0
    if args.cmd == "run":
        df, _ = read_table(args.data)
        rep = PRIV.audit_dataframe(df)
        keep = {c.strip() for c in args.keep.split(",") if c.strip()}
        dropped = rep.to_drop(keep)
        df = normalize(df.drop(columns=dropped))
        plan = plan_from_dict(json.loads(Path(args.plan).read_text()))
        lock = json.loads(Path(args.lock).read_text()) if args.lock else None
        res = run_analysis(df, plan, lock)
        import datetime as dt
        pkg = build_package(res, lock=lock, priv={"dropped": dropped}, include_data=args.include_data, df_input=df,
                            repo_url=args.repo_url, generated_on=dt.date.today().isoformat())
        base = write_package(pkg, args.out)
        print(f"wrote {base}  verification={'PASSED' if pkg.verification['ok'] else 'FAILED'}  privacy gate={'clean' if not pkg.gate else pkg.gate}")
        return 0 if pkg.ready else 2
    if args.cmd == "reproduce":
        out = reproduce(args.package)
        print(out["summary"])
        return 0 if out["ok"] else 1
    if args.cmd == "llm-check":
        import os
        from . import llm as L
        cfg = L.LLMConfig(provider=args.provider, model=args.model, base_url=args.base_url, api_key=args.api_key or os.environ.get("SU_LLM_API_KEY", ""))
        if args.provider in ("ollama", "lmstudio", "openai_compatible"):
            try:
                models = L.list_models(cfg)
                print(f"connected: {len(models)} model(s): {', '.join(models[:8])}")
                if not cfg.model and models:
                    cfg.model = models[0]
                    print(f"using {cfg.model}")
            except RuntimeError as e:
                print(f"FAIL connection: {e}")
                return 1
        df = normalize(make_demo())
        plan = demo_plan()
        res = run_analysis(df.drop(columns=PRIV.audit_dataframe(df).to_drop()), plan, None, with_spec=False)
        try:
            out = L.draft_narrative(res, L.LLM(cfg))
        except Exception as e:
            print(f"FAIL narrative: {e}")
            return 1
        from .report import _fill
        print("PASS. Summary the model wrote (numbers filled in from the tables):")
        print(_fill(out["summary"], res.effects))
        return 0
    if args.cmd == "check":
        bad = 0
        for d in sorted(p for p in Path(args.studies).iterdir() if (p / "study.json").exists()):
            files = {str(f.relative_to(d)): f.read_bytes() for f in d.rglob("*") if f.is_file()}
            issues = PRIV.gate_files(files, allow_data="data/analysis_input.csv" in files)
            out = reproduce(d)
            status = "ok" if (not issues and out["ok"]) else "FAILED"
            bad += status != "ok"
            print(f"{d.name}: {status}")
            for i in issues:
                print(f"  privacy: {i.path}: {i.problem}")
            if not out["ok"]:
                print("  " + out["summary"].replace("\n", "\n  "))
        return 1 if bad else 0
    if args.cmd == "meta":
        eff = LIB.local_effects(args.studies)
        print(META.meta_by_construct(eff).round(3).to_string(index=False) if len(eff) else "no studies found")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
