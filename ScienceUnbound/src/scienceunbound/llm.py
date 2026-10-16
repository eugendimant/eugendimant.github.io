"""Optional language-model help. Everything works without it.

What a model may see: column NAMES, the plan text the author pastes, and structure of the results (ids, labels, verdicts).
Never a data row. What a model may do: draft a plan for the author to review, and write summary prose. It never writes a number:
prose carries placeholders like {{H1:info.es}} that report.py fills from the tables, and any literal digit rejects the draft.
Nothing a model returns is ever executed.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import verify as VER
from .schema import Plan, plan_from_dict, validate_plan

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_:\-.x]+?)\.([a-z_]+)\s*\}\}")
ALLOWED_FIELDS = {"es", "es_ci_low", "es_ci_high", "p", "p_adj", "n", "mde_es", "tost_p", "estimate"}


LOCAL_URLS = {"ollama": "http://localhost:11434/v1", "lmstudio": "http://localhost:1234/v1"}
OPENAI_STYLE = ("openai_compatible", "ollama", "lmstudio")
ALWAYS_BANNED = re.compile(r"\b(no effect|proves?|proved|definitive(ly)?|confirms? that|did not work|failed to work)\b", re.I)
CAUSAL = re.compile(r"\b(caus(e|ed|es|ing)|led to|leads to|effects? of|improv(ed|es|ing)|boost(ed|s)?|increased|reduced|raised)\b", re.I)


class BudgetExceeded(RuntimeError):
    pass


class NarrativeRejected(ValueError):
    pass


@dataclass
class LLMConfig:
    provider: str = "none"            # none | anthropic | openai_compatible | ollama | lmstudio | mock
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    max_tokens: int = 1500
    budget_usd: float = 0.25
    price_in_per_mtok: float = 0.0    # set both prices to enable the dollar budget; otherwise max_calls applies
    price_out_per_mtok: float = 0.0
    max_calls: int = 6
    zero_retention: bool = True
    mock_responses: list[str] = field(default_factory=list)


class LLM:
    def __init__(self, cfg: LLMConfig, client: httpx.Client | None = None):
        self.cfg, self.client = cfg, client
        self.spent_usd = 0.0
        self.calls: list[dict] = []

    @property
    def enabled(self) -> bool:
        return self.cfg.provider != "none"

    def _estimate(self, system: str, user: str) -> float:
        c = self.cfg
        return ((len(system) + len(user)) / 4) * c.price_in_per_mtok / 1e6 + c.max_tokens * c.price_out_per_mtok / 1e6

    def complete(self, system: str, user: str) -> str:
        c = self.cfg
        if c.provider == "none":
            raise RuntimeError("no language model configured")
        if len(self.calls) >= c.max_calls:
            raise BudgetExceeded(f"call limit reached ({c.max_calls})")
        if (c.price_in_per_mtok or c.price_out_per_mtok) and self.spent_usd + self._estimate(system, user) > c.budget_usd:
            raise BudgetExceeded(f"the next call could exceed the budget of ${c.budget_usd:.2f}")
        tin = tout = 0
        if c.provider == "mock":
            text = c.mock_responses[len(self.calls)] if len(self.calls) < len(c.mock_responses) else "{}"
        elif c.provider == "anthropic":
            url = (c.base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
            r = (self.client or httpx).post(url, timeout=120, headers={"x-api-key": c.api_key, "anthropic-version": "2023-06-01"},
                                            json={"model": c.model, "max_tokens": c.max_tokens, "system": system,
                                                  "messages": [{"role": "user", "content": user}]})
            self._raise(r)
            j = r.json()
            text = "".join(b.get("text", "") for b in j.get("content", []))
            tin, tout = j.get("usage", {}).get("input_tokens", 0), j.get("usage", {}).get("output_tokens", 0)
        elif c.provider in OPENAI_STYLE:
            base = (c.base_url or LOCAL_URLS.get(c.provider, "")).rstrip("/")
            if not base or not c.model:
                raise RuntimeError("choose a model and a base URL first")
            body: dict[str, Any] = {"model": c.model, "max_tokens": c.max_tokens, "temperature": 0.2,
                                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if c.zero_retention and "openrouter" in base:
                body["provider"] = {"data_collection": "deny"}
            headers = {"Authorization": f"Bearer {c.api_key}"} if c.api_key else {}
            r = (self.client or httpx).post(base + "/chat/completions", timeout=600, headers=headers, json=body)
            self._raise(r)
            j = r.json()
            text = j["choices"][0]["message"]["content"] or ""
            tin, tout = j.get("usage", {}).get("prompt_tokens", 0), j.get("usage", {}).get("completion_tokens", 0)
        else:
            raise RuntimeError(f"unknown provider {c.provider}")
        cost = tin * c.price_in_per_mtok / 1e6 + tout * c.price_out_per_mtok / 1e6
        self.spent_usd += cost
        self.calls.append({"sha256_of_request": hashlib.sha256((system + "\n" + user).encode()).hexdigest(), "tokens_in": tin,
                           "tokens_out": tout, "cost_usd": round(cost, 6), "model": c.model})
        return text

    @staticmethod
    def _raise(r: httpx.Response):
        if r.status_code >= 400:
            raise RuntimeError(f"the model API answered HTTP {r.status_code}")   # never echo headers or the key


def list_models(cfg: LLMConfig, client: httpx.Client | None = None) -> list[str]:
    """Model names the server offers. Doubles as a connection test for local servers."""
    base = (cfg.base_url or LOCAL_URLS.get(cfg.provider, "")).rstrip("/")
    if cfg.provider not in OPENAI_STYLE or not base:
        raise RuntimeError("model listing works for Ollama, LM Studio and OpenAI-style servers")
    try:
        r = (client or httpx).get(base + "/models", timeout=8, headers={"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {})
    except httpx.HTTPError:
        raise RuntimeError(f"cannot reach {base}. Is the server running?") from None
    if r.status_code >= 400:
        raise RuntimeError(f"the server answered HTTP {r.status_code}")
    return sorted(m.get("id", "") for m in r.json().get("data", []) if m.get("id"))


def extract_json(text: str) -> Any:
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


# ------------------------------------------------------------------ narrative
NARRATIVE_SYSTEM = """You write two parts of a research report: a summary (at most 120 words) and 3 to 6 limitations.
Hard rules:
- NEVER write a digit. Write every number as a placeholder {{ANALYSIS_ID.field}} with field one of: es, es_ci_low, es_ci_high, p, p_adj, n, mde_es, tost_p, estimate. Example: {{H1:info.es}}.
- Only use analysis ids from the table you are given. Use the verdict you are given; do not upgrade it.
- If the design is observational, never use causal words (effect, caused, led to, improved). Use "association".
- 'inconclusive' means the study could not tell; say so. Never say an inconclusive result shows no effect.
- Reply with JSON only: {"summary": "...", "limitations": ["...", "..."]}"""


def narrative_payload(res) -> dict:
    return {"title": res.plan.title, "design": res.plan.design,
            "estimates": [{"id": r["analysis_id"], "label": r["label"], "outcome": r["outcome"], "contrast": r["contrast"],
                           "verdict": r["verdict"], "confirmatory": bool(r["confirmatory"]), "tag": r["tag"]}
                          for r in res.effects.to_dict("records")]}


def validate_narrative(obj: Any, eff, design: str = "randomized") -> dict:
    if not isinstance(obj, dict) or not isinstance(obj.get("summary"), str) or not isinstance(obj.get("limitations"), list):
        raise NarrativeRejected("the reply does not have the required shape")
    texts = [obj["summary"]] + [str(x) for x in obj["limitations"]]
    if len(obj["summary"]) > 1200 or len(obj["limitations"]) > 8 or any(len(t) > 400 for t in texts[1:]):
        raise NarrativeRejected("the reply is too long")
    ids = set(eff["analysis_id"])
    for t in texts:
        for m in PLACEHOLDER.finditer(t):
            if m.group(1) not in ids or m.group(2) not in ALLOWED_FIELDS:
                raise NarrativeRejected(f"unknown placeholder {m.group(0)}")
        bare = PLACEHOLDER.sub(" ", t)
        bad = ALWAYS_BANNED.search(bare) or (CAUSAL.search(bare) if design != "randomized" else None)
        if bad:
            raise NarrativeRejected(f"the wording '{bad.group(0)}' is not supported by this design or by an inconclusive result")
        digits = VER.NUM.findall(bare)
        if digits:
            raise NarrativeRejected(f"the draft contains literal numbers {digits[:3]}; numbers must be placeholders")
    return {"summary": obj["summary"], "limitations": [str(x) for x in obj["limitations"]]}


def draft_narrative(res, llm: LLM, retries: int = 2) -> dict:
    """Ask, validate, and on rejection ask again with the reason (small local models often need one retry)."""
    payload = narrative_payload(res)
    last: Exception | None = None
    for _ in range(retries + 1):
        msg = json.dumps(payload if last is None else {**payload, "your_previous_reply_was_rejected_because": str(last)})
        raw = llm.complete(NARRATIVE_SYSTEM, msg)
        try:
            return validate_narrative(extract_json(raw), res.effects, res.plan.design)
        except (NarrativeRejected, ValueError) as e:
            last = e
    raise NarrativeRejected(f"{last} (after {retries + 1} attempts)")


# ------------------------------------------------------------------ plan drafting
PLAN_SYSTEM = """Convert the pre-analysis plan text into JSON for this schema. You see column names only, never data.
Return JSON only: {"design":"randomized|observational","arm_column":"","control_level":"",
"outcomes":[{"name":"","items":["col"],"reverse":[],"scale":[lo,hi]|null,"kind":"single|index"}],
"hypotheses":[{"id":"H1","label":"","outcome":"<outcome name>","predictor":"","predictor_type":"categorical|continuous",
"direction":"positive|negative|two_sided","covariates":[],"se":"HC2|HC3|classical|cluster","cluster":"","moderator":"",
"confirmatory":true,"construct":"","sesoi":null}],
"exclusions":[{"column":"","op":"==|!=|>|>=|<|<=|in|not_in|isna|notna","value":null,"reason":""}],
"alpha":0.05,"multiplicity":"holm|bh|none"}
Use only column names from the list. If the text is silent on something, leave the default and do not invent it.
An exclusion REMOVES rows where its condition is true."""


def draft_plan(text: str, columns: list[str], llm: LLM, retries: int = 1) -> tuple[Plan | None, list[str]]:
    payload = {"plan_text": text[:12000], "columns": columns}
    err = ""
    for _ in range(retries + 1):
        raw = llm.complete(PLAN_SYSTEM, json.dumps(payload if not err else {**payload, "your_previous_reply_was_rejected_because": err}))
        try:
            d = extract_json(raw)
            if not isinstance(d, dict):
                raise ValueError("the reply is not a JSON object")
            if not (d.get("outcomes") or d.get("hypotheses")):
                raise ValueError("the reply contains no outcomes or hypotheses")
            plan = plan_from_dict(d)
        except (ValueError, TypeError) as e:
            err = str(e)
            continue
        return plan, validate_plan(plan, columns)
    return None, [err]
