"""The analysis plan as plain data. Everything the pipeline does is driven by this structure, never by model-written code."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, fields
from typing import Any

SE_TYPES = ("HC2", "HC3", "classical", "cluster")
DIRECTIONS = ("two_sided", "positive", "negative")
MULTIPLICITY = ("holm", "bh", "none")
EXCLUSION_OPS = ("==", "!=", ">", ">=", "<", "<=", "in", "not_in", "isna", "notna")
DESIGNS = ("randomized", "observational")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,23}$")


def canon_level(v: Any) -> str:
    """Canonical string for a category value: 1, 1.0 and "1.0" all become "1"; missing becomes ""."""
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    s = str(v).strip()
    if s.lower() in ("nan", "<na>", "none"):
        return ""
    try:
        f = float(s)
        if math.isfinite(f) and f.is_integer():
            return str(int(f))
    except ValueError:
        pass
    return s


@dataclass
class Outcome:
    name: str
    items: list[str] = field(default_factory=list)      # source columns
    reverse: list[str] = field(default_factory=list)    # items to reverse-code (needs scale)
    scale: list[float] | None = None                    # [lowest, highest] point of the item scale
    kind: str = "single"                                # single | index (mean of items; all items required)


@dataclass
class Exclusion:
    """Rows where the condition is TRUE are removed. Structured on purpose: no expression is ever evaluated."""
    column: str
    op: str
    value: Any = None
    reason: str = ""


@dataclass
class Hypothesis:
    id: str
    label: str
    outcome: str
    predictor: str = ""               # "" = the plan's arm column
    predictor_type: str = "categorical"   # categorical | continuous
    reference: str = ""               # "" = the plan's control level
    levels: list[str] = field(default_factory=list)     # [] = every other level, one contrast each
    direction: str = "two_sided"
    covariates: list[str] = field(default_factory=list)
    se: str = "HC2"
    cluster: str = ""
    moderator: str = ""               # if set, the tested effect is the predictor x moderator interaction
    confirmatory: bool = True
    construct: str = ""               # free-text tag used to pool studies in the meta-analysis
    sesoi: float | None = None        # smallest effect of interest: SD units (g) or |r|; enables the equivalence test
    weights: str = ""                 # optional survey-weight column (analytic weights in weighted least squares, robust errors)


@dataclass
class Plan:
    title: str = ""
    slug: str = ""
    authors: list[str] = field(default_factory=list)
    summary: str = ""
    design: str = "randomized"
    arm_column: str = ""
    control_level: str = ""
    arm_labels: dict[str, str] = field(default_factory=dict)
    expected_allocation: dict[str, float] = field(default_factory=dict)   # level -> share; empty = equal
    outcomes: list[Outcome] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    exclusions: list[Exclusion] = field(default_factory=list)
    alpha: float = 0.05
    multiplicity: str = "holm"
    population: str = ""
    registration_url: str = ""        # OSF, AsPredicted, AEA registry, ...: listed, never verified by the tool
    data_collected_through: str = ""  # ISO date the authors declare data collection ended
    deviation_notes: dict[str, str] = field(default_factory=dict)       # hypothesis id -> reason for a deviation
    seed: int = 20260101


def _build(cls, d: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (d or {}).items() if k in names})


def plan_from_dict(d: dict) -> Plan:
    d = dict(d or {})
    outcomes = [_build(Outcome, o) for o in d.pop("outcomes", [])]
    hyps = [_build(Hypothesis, h) for h in d.pop("hypotheses", [])]
    excl = [_build(Exclusion, e) for e in d.pop("exclusions", [])]
    plan = _build(Plan, d)
    plan.outcomes, plan.hypotheses, plan.exclusions = outcomes, hyps, excl
    plan.control_level = canon_level(plan.control_level)
    for h in plan.hypotheses:
        h.reference = canon_level(h.reference)
        h.levels = [canon_level(x) for x in h.levels]
    plan.arm_labels = {canon_level(k): str(v) for k, v in plan.arm_labels.items()}
    plan.expected_allocation = {canon_level(k): float(v) for k, v in plan.expected_allocation.items()}
    return plan


def plan_to_dict(plan: Plan) -> dict:
    return json.loads(json.dumps(asdict(plan), default=str))


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def plan_hash(plan: Plan | dict) -> str:
    d = plan_to_dict(plan) if isinstance(plan, Plan) else plan
    return hashlib.sha256(canonical_json(d).encode("utf-8")).hexdigest()


def arm_label(plan: Plan, level: str) -> str:
    return plan.arm_labels.get(level) or level


def validate_plan(plan: Plan, columns: list[str] | None = None) -> list[str]:
    """Return human-readable problems; an empty list means the plan can run."""
    p: list[str] = []
    cols = set(columns) if columns is not None else None

    def need(col: str, what: str):
        if cols is not None and col and col not in cols:
            p.append(f"{what}: column '{col}' is not in the data")

    if not SLUG_RE.match(plan.slug or ""):
        p.append("slug must be 2-61 characters: lowercase letters, digits, hyphens")
    if not plan.title.strip():
        p.append("the study needs a title")
    if plan.design not in DESIGNS:
        p.append(f"design must be one of {DESIGNS}")
    if not (0 < plan.alpha <= 0.5):
        p.append("alpha must be between 0 and 0.5")
    if plan.multiplicity not in MULTIPLICITY:
        p.append(f"multiplicity must be one of {MULTIPLICITY}")
    if plan.design == "randomized":
        if not plan.arm_column:
            p.append("a randomized design needs an arm column")
        if plan.arm_column and not plan.control_level:
            p.append("a randomized design needs a control level")
        need(plan.arm_column, "arm column")
    names = [o.name for o in plan.outcomes]
    if len(set(names)) != len(names):
        p.append("outcome names must be unique")
    for o in plan.outcomes:
        if not o.name:
            p.append("every outcome needs a name")
        if o.kind not in ("single", "index"):
            p.append(f"outcome {o.name}: kind must be single or index")
        if not o.items:
            p.append(f"outcome {o.name}: choose at least one column")
        if o.kind == "index" and len(o.items) < 2:
            p.append(f"outcome {o.name}: an index needs at least two items")
        if o.reverse and not (o.scale and len(o.scale) == 2 and o.scale[0] < o.scale[1]):
            p.append(f"outcome {o.name}: reverse-coded items need a scale [low, high]")
        for it in o.items:
            need(it, f"outcome {o.name}")
        if cols is not None and o.name in cols and not (o.kind == "single" and o.items == [o.name]):
            p.append(f"outcome name '{o.name}' collides with a data column; rename the outcome")
    ids = [h.id for h in plan.hypotheses]
    if len(set(ids)) != len(ids):
        p.append("hypothesis ids must be unique")
    for h in plan.hypotheses:
        if not ID_RE.match(h.id or ""):
            p.append(f"hypothesis id '{h.id}': start with a letter, then letters, digits or underscore (max 24)")
        if h.outcome not in names:
            p.append(f"{h.id}: outcome '{h.outcome}' is not defined")
        if h.direction not in DIRECTIONS:
            p.append(f"{h.id}: direction must be one of {DIRECTIONS}")
        if h.se not in SE_TYPES:
            p.append(f"{h.id}: se must be one of {SE_TYPES}")
        if h.se == "cluster" and not h.cluster:
            p.append(f"{h.id}: cluster-robust errors need a cluster column")
        if h.predictor_type not in ("categorical", "continuous"):
            p.append(f"{h.id}: predictor_type must be categorical or continuous")
        pred = h.predictor or plan.arm_column
        if not pred:
            p.append(f"{h.id}: no predictor and the plan has no arm column")
        need(pred, f"{h.id} predictor")
        for c in h.covariates:
            need(c, f"{h.id} covariate")
        need(h.moderator, f"{h.id} moderator")
        need(h.weights, f"{h.id} weights")
        if h.weights and (h.weights == pred or h.weights in h.covariates):
            p.append(f"{h.id}: the weight column cannot also be the predictor or a covariate")
        need(h.cluster, f"{h.id} cluster")
        if h.sesoi is not None and not (h.sesoi > 0):
            p.append(f"{h.id}: the smallest effect of interest must be positive")
        if pred in h.covariates:
            p.append(f"{h.id}: the predictor cannot also be a covariate")
        if h.moderator and h.predictor_type == "continuous":
            p.append(f"{h.id}: moderation is supported for categorical predictors only")
    for e in plan.exclusions:
        if e.op not in EXCLUSION_OPS:
            p.append(f"exclusion on '{e.column}': operator must be one of {EXCLUSION_OPS}")
        need(e.column, "exclusion")
    if not plan.hypotheses:
        p.append("add at least one hypothesis")
    return p
