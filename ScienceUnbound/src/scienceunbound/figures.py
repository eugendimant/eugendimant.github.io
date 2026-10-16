"""Static figures for the report (PNG bytes)."""
from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

COLORS = {"supported": "#1b7f5c", "equivalent": "#2b6cb0", "inconclusive": "#6b7280", "opposite": "#b42318"}


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def forest(effects: pd.DataFrame) -> bytes | None:
    d = effects[effects["es_metric"].isin(["g", "r", "g_int"])].reset_index(drop=True)
    if d.empty:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 0.52 * len(d) + 1.4))
    ys = np.arange(len(d))[::-1]
    for y, r in zip(ys, d.to_dict("records")):
        if r.get("sesoi") and r["es_metric"] in ("g", "r"):
            ax.add_patch(plt.Rectangle((-r["sesoi"], y - 0.36), 2 * r["sesoi"], 0.72, color="#dbeafe", zorder=0, lw=0))
        c = COLORS.get(r["verdict"], "#6b7280")
        ax.plot([r["es_ci_low"], r["es_ci_high"]], [y, y], color=c, lw=2, zorder=2, solid_capstyle="round")
        ax.plot(r["es"], y, "o", color=c, ms=6, zorder=3)
    ax.axvline(0, color="#111827", lw=0.8)
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{r['analysis_id']}" + ("  (exploratory)" if not r["confirmatory"] else "") for r in d.to_dict("records")], fontsize=8)
    ax.set_xlabel("Standardised effect with 95% CI (g, r or interaction in SD units). Shaded: smallest effect of interest", fontsize=8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, label=k) for k, c in COLORS.items()]
    ax.legend(handles=handles, fontsize=7, frameon=False, loc="lower right")
    return _png(fig)


def spec_curves(spec: pd.DataFrame, alpha: float, max_panels: int = 6) -> bytes | None:
    if spec is None or spec.empty:
        return None
    ids = list(dict.fromkeys(spec["analysis_id"]))[:max_panels]
    cols = min(3, len(ids))
    rows = int(np.ceil(len(ids) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.2 * cols, 2.4 * rows), squeeze=False)
    for ax, aid in zip(axes.ravel(), ids):
        g = spec[spec["analysis_id"] == aid].sort_values("es").reset_index(drop=True)
        sig = g["p"] < alpha
        ax.vlines(g.index, g["ci_low"], g["ci_high"], color=np.where(sig, "#1b7f5c", "#9ca3af"), lw=1.2)
        ax.plot(g.index, g["es"], "o", ms=3, color="#111827")
        ax.axhline(0, color="#111827", lw=0.6)
        ax.set_title(aid, fontsize=8)
        ax.set_xticks([])
        ax.tick_params(labelsize=7)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    for ax in axes.ravel()[len(ids):]:
        ax.axis("off")
    fig.supylabel("effect size", fontsize=8)
    fig.suptitle("Specification curves: every defensible analysis choice (green: p below alpha)", fontsize=8)
    return _png(fig)


def meta_forest(rows: pd.DataFrame, pooled: dict, label: str) -> bytes | None:
    if rows.empty:
        return None
    fig, ax = plt.subplots(figsize=(7, 0.4 * len(rows) + 1.8))
    ys = np.arange(len(rows) + 1)[::-1]
    for y, r in zip(ys[1:], rows.to_dict("records")):
        ax.plot([r["lo"], r["hi"]], [y, y], color="#6b7280", lw=1.6)
        ax.plot(r["yi"], y, "s", color="#111827", ms=5)
    p = pooled
    ax.fill([p["ci_low"], p["pooled"], p["ci_high"], p["pooled"]], [ys[0], ys[0] + 0.3, ys[0], ys[0] - 0.3], color="#1b7f5c")
    ax.axvline(0, color="#111827", lw=0.7)
    ax.set_yticks(ys)
    ax.set_yticklabels(["Pooled (random effects)"] + list(rows["label"]), fontsize=8)
    ax.set_xlabel(label, fontsize=8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    return _png(fig)
