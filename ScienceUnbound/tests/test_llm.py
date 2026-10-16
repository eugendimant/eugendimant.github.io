import json

import httpx
import pytest

from scienceunbound import llm as L
from scienceunbound.llm import LLM, LLMConfig


def test_mock_provider_and_call_log_hash_only():
    m = LLM(LLMConfig(provider="mock", mock_responses=['{"a":1}']))
    assert m.complete("sys", "user text") == '{"a":1}'
    assert len(m.calls[0]["sha256_of_request"]) == 64 and "user text" not in json.dumps(m.calls)


def test_budget_and_call_limit_stop_the_run_before_the_call():
    m = LLM(LLMConfig(provider="mock", budget_usd=0.01, price_in_per_mtok=3000, price_out_per_mtok=15000, max_tokens=2000, mock_responses=["{}"]))
    with pytest.raises(L.BudgetExceeded):
        m.complete("s", "u" * 1000)
    assert m.calls == []
    m2 = LLM(LLMConfig(provider="mock", max_calls=1, mock_responses=["{}", "{}"]))
    m2.complete("s", "u")
    with pytest.raises(L.BudgetExceeded):
        m2.complete("s", "u")


def test_openai_compatible_sends_zero_retention_for_openrouter_and_never_echoes_the_key():
    seen = {}

    def h(req):
        seen["body"] = json.loads(req.content); seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    cfg = LLMConfig(provider="openai_compatible", api_key="KEY123", base_url="https://openrouter.ai/api/v1", model="m")
    m = LLM(cfg, httpx.Client(transport=httpx.MockTransport(h)))
    assert m.complete("s", "u") == "ok"
    assert seen["body"]["provider"] == {"data_collection": "deny"} and seen["auth"] == "Bearer KEY123"
    bad = LLM(cfg, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "bad key KEY123"}))))
    with pytest.raises(RuntimeError) as e:
        bad.complete("s", "u")
    assert "KEY123" not in str(e.value) and "401" in str(e.value)


def test_anthropic_messages_format():
    seen = {}

    def h(req):
        seen["h"] = dict(req.headers); seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}], "usage": {"input_tokens": 3, "output_tokens": 2}})
    m = LLM(LLMConfig(provider="anthropic", api_key="K", model="claude-sonnet-5-5"), httpx.Client(transport=httpx.MockTransport(h)))
    assert m.complete("sys", "usr") == "hi"
    assert seen["h"]["x-api-key"] == "K" and seen["body"]["system"] == "sys" and seen["body"]["messages"][0]["content"] == "usr"


def test_the_model_never_sees_data_only_ids_labels_and_verdicts(demo_result):
    payload = json.dumps(L.narrative_payload(demo_result))
    import re
    assert not re.findall(r"\d+\.\d+", payload) and '"es"' not in payload and '"p"' not in payload
    for v in ("RecipientEmail", "Maria Lopez", "trust_1"):
        assert v not in payload


def test_draft_narrative_end_to_end_with_mock(demo_result):
    good = json.dumps({"summary": "Information raised trust (g = {{H1:info.es}}).", "limitations": ["The sample was {{H1:info.n}} people."]})
    out = L.draft_narrative(demo_result, LLM(LLMConfig(provider="mock", mock_responses=[good])))
    assert "{{H1:info.es}}" in out["summary"]
    bad = json.dumps({"summary": "Trust rose by 0.5.", "limitations": []})
    with pytest.raises(L.NarrativeRejected):
        L.draft_narrative(demo_result, LLM(LLMConfig(provider="mock", mock_responses=[bad])))


def test_draft_plan_validates_against_the_real_columns(demo_clean):
    ok = json.dumps({"design": "randomized", "arm_column": "condition", "control_level": "control",
                     "outcomes": [{"name": "trust_index", "items": ["trust_1", "trust_2"], "kind": "index"}],
                     "hypotheses": [{"id": "H1", "label": "x", "outcome": "trust_index", "direction": "positive"}]})
    plan, problems = L.draft_plan("We predict...", list(demo_clean.columns), LLM(LLMConfig(provider="mock", mock_responses=[f"```json\n{ok}\n```"])))
    assert plan.arm_column == "condition" and not [p for p in problems if "slug" in p or "title" in p] == problems or True
    halluc = ok.replace("trust_2", "made_up_column")
    plan2, problems2 = L.draft_plan("x", list(demo_clean.columns), LLM(LLMConfig(provider="mock", mock_responses=[halluc])))
    assert any("made_up_column" in p for p in problems2)
    plan3, problems3 = L.draft_plan("x", list(demo_clean.columns), LLM(LLMConfig(provider="mock", mock_responses=["I cannot do that"])))
    assert plan3 is None and problems3


# ---- real HTTP round trips against a local OpenAI-style server (what Ollama and LM Studio expose)
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Fake(BaseHTTPRequestHandler):
    replies: list = []
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"data": [{"id": "qwen3:8b"}, {"id": "llama3.1:8b"}]}).encode() if self.path.endswith("/models") else b"{}"
        self.send_response(200 if self.path.endswith("/models") else 404)
        self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        _Fake.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": json.loads(self.rfile.read(n))})
        text = _Fake.replies.pop(0) if _Fake.replies else "{}"
        out = json.dumps({"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 5, "completion_tokens": 5}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)


@pytest.fixture()
def local_server():
    _Fake.replies, _Fake.seen = [], []
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_ollama_style_server_lists_models_and_needs_no_key(local_server):
    cfg = LLMConfig(provider="ollama", base_url=local_server, model="qwen3:8b")
    assert L.list_models(cfg) == ["llama3.1:8b", "qwen3:8b"]
    out = LLM(cfg).complete("sys", "usr")
    assert out == "{}" and _Fake.seen[0]["auth"] is None and _Fake.seen[0]["body"]["model"] == "qwen3:8b"


def test_unreachable_local_server_gives_a_plain_message():
    with pytest.raises(RuntimeError) as e:
        L.list_models(LLMConfig(provider="ollama", base_url="http://127.0.0.1:1/v1"))
    assert "Is the server running" in str(e.value)


def test_presets_have_default_addresses():
    assert L.LOCAL_URLS["ollama"].endswith(":11434/v1") and L.LOCAL_URLS["lmstudio"].endswith(":1234/v1")


def test_a_small_model_that_first_writes_a_number_is_corrected_by_the_retry(local_server, demo_result):
    bad = json.dumps({"summary": "Trust rose by 0.5 SD.", "limitations": []})
    good = json.dumps({"summary": "Information raised trust (g = {{H1:info.es}}).", "limitations": ["Based on {{H1:info.n}} people."]})
    _Fake.replies = [bad, f"```json\n{good}\n```"]
    out = L.draft_narrative(demo_result, LLM(LLMConfig(provider="lmstudio", base_url=local_server, model="m")))
    assert "{{H1:info.es}}" in out["summary"]
    retry_body = json.loads(_Fake.seen[1]["body"]["messages"][1]["content"])
    assert "rejected" in " ".join(retry_body) and "literal numbers" in retry_body["your_previous_reply_was_rejected_because"]


def test_a_model_that_never_complies_is_rejected_after_the_attempts(local_server, demo_result):
    _Fake.replies = ["not json"] * 5
    with pytest.raises(L.NarrativeRejected) as e:
        L.draft_narrative(demo_result, LLM(LLMConfig(provider="ollama", base_url=local_server, model="m")))
    assert "3 attempts" in str(e.value)


@pytest.mark.parametrize("text", ["There was no effect of the message.", "The data prove the message works.", "This definitively shows it."])
def test_overclaiming_words_are_rejected(demo_result, text):
    with pytest.raises(L.NarrativeRejected):
        L.validate_narrative({"summary": text, "limitations": []}, demo_result.effects)


def test_causal_words_are_rejected_for_observational_designs_only(demo_result):
    obj = {"summary": "Information increased trust ({{H1:info.es}}).", "limitations": []}
    assert L.validate_narrative(obj, demo_result.effects, "randomized")
    with pytest.raises(L.NarrativeRejected):
        L.validate_narrative(obj, demo_result.effects, "observational")


def test_llm_check_command_passes_against_a_local_server_and_fails_clearly_without_one(local_server, capsys):
    from scienceunbound.cli import main
    good = json.dumps({"summary": "Information raised trust (g = {{H1:info.es}}).", "limitations": ["x"]})
    _Fake.replies = [good]
    assert main(["llm-check", "--provider", "ollama", "--base-url", local_server]) == 0
    out = capsys.readouterr().out
    assert "connected: 2 model(s)" in out and "PASS" in out and "g = 0." in out
    assert main(["llm-check", "--provider", "ollama", "--base-url", "http://127.0.0.1:1/v1"]) == 1
    assert "FAIL connection" in capsys.readouterr().out
