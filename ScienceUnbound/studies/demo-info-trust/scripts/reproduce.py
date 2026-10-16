"""Re-run this study and check every number.

    pip install "scienceunbound @ git+https://github.com/eugendimant/ScienceUnbound"
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
