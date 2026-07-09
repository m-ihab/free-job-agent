"""Tests for the free-tier cloud LLM fallback router (job-public tasks only).

The router must be hermetic-by-default: with no ``JOB_AGENT_USE_FREE_LLM`` env
flag it never touches the network and always returns ``None``. Transport is
exercised through a stub ``requests`` object patched onto the module, matching
the ``free_apis.requests`` / ``ai.requests`` seam convention used elsewhere.
"""
from __future__ import annotations

import json

import pytest

import job_agent.llm_providers as lp


_ENV_KEYS = [
    "JOB_AGENT_USE_FREE_LLM",
    "JOB_AGENT_FREE_LLM_ORDER",
    "JOB_AGENT_FREE_LLM_TIMEOUT",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "CEREBRAS_API_KEY",
    "GEMINI_API_KEY",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for name in lp.PROVIDERS:
        monkeypatch.delenv(f"JOB_AGENT_FREE_LLM_MODEL_{name.upper()}", raising=False)


class _Resp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> dict:
        return self._payload


def _chat_payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


class _StubRequests:
    """Minimal requests stand-in recording every POST."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, json=None, headers=None, timeout=None):  # noqa: A002 (match requests API)
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


# ── availability gates ────────────────────────────────────────────────────────


def test_disabled_by_default_returns_none(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    stub = _StubRequests([])
    monkeypatch.setattr(lp, "requests", stub)
    assert lp.cloud_enabled() is False
    assert lp.maybe_cloud_json("prompt", task="classify") is None
    assert stub.calls == []


def test_enabled_without_keys_is_not_available(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    assert lp.available_cloud_providers() == []
    assert lp.cloud_enabled() is False


def test_cloud_enabled_with_flag_and_key(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert lp.cloud_enabled() is True


# ── privacy: task allowlist ───────────────────────────────────────────────────


def test_candidate_tasks_never_go_to_cloud(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    stub = _StubRequests([_Resp(_chat_payload('{"a": 1}'))])
    monkeypatch.setattr(lp, "requests", stub)
    for task in ["fit_analysis", "cover_letter_body", "tailored_summary", "chat", "outreach", "general"]:
        assert lp.maybe_cloud_json("prompt", task=task) is None
    assert stub.calls == []  # nothing may leave the machine for candidate tasks


def test_job_public_tasks_are_allowlisted():
    assert lp.is_job_public_task("classify") is True
    assert lp.is_job_public_task("summarize") is True
    assert lp.is_job_public_task("fit_analysis") is False


# ── provider ordering + fallback chain ────────────────────────────────────────


def test_provider_order_respects_env_and_keys(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("MISTRAL_API_KEY", "m")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("JOB_AGENT_FREE_LLM_ORDER", "mistral,groq,unknown")
    names = [p.name for p in lp.available_cloud_providers()]
    assert names == ["mistral", "groq"]


def test_fallback_moves_to_next_provider_on_error(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("MISTRAL_API_KEY", "m")
    monkeypatch.setenv("JOB_AGENT_FREE_LLM_ORDER", "groq,mistral")
    stub = _StubRequests([RuntimeError("rate limited"), _Resp(_chat_payload('{"ok": true}'))])
    monkeypatch.setattr(lp, "requests", stub)
    result = lp.maybe_cloud_json("job text only", task="classify")
    assert result == {"ok": True}
    assert len(stub.calls) == 2
    assert "groq" in stub.calls[0]["url"]
    assert "mistral" in stub.calls[1]["url"]


def test_returns_none_when_all_providers_fail(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    stub = _StubRequests([RuntimeError("boom")])
    monkeypatch.setattr(lp, "requests", stub)
    assert lp.maybe_cloud_json("prompt", task="summarize") is None


def test_returns_none_when_requests_missing(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setattr(lp, "requests", None)
    assert lp.maybe_cloud_json("prompt", task="classify") is None


# ── response parsing ──────────────────────────────────────────────────────────


def test_parses_code_fenced_json(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    fenced = "```json\n" + json.dumps({"tldr": "ok"}) + "\n```"
    stub = _StubRequests([_Resp(_chat_payload(fenced))])
    monkeypatch.setattr(lp, "requests", stub)
    assert lp.maybe_cloud_json("prompt", task="summarize") == {"tldr": "ok"}


def test_invalid_json_falls_through_to_none(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    stub = _StubRequests([_Resp(_chat_payload("not json at all"))])
    monkeypatch.setattr(lp, "requests", stub)
    assert lp.maybe_cloud_json("prompt", task="classify") is None


def test_request_carries_auth_and_model(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "secret-key")
    monkeypatch.setenv("JOB_AGENT_FREE_LLM_MODEL_GROQ", "custom-model")
    stub = _StubRequests([_Resp(_chat_payload('{"a": 1}'))])
    monkeypatch.setattr(lp, "requests", stub)
    lp.maybe_cloud_json("prompt", task="classify", max_output_tokens=99)
    call = stub.calls[0]
    assert call["headers"]["Authorization"] == "Bearer secret-key"
    assert call["json"]["model"] == "custom-model"
    assert call["json"]["max_tokens"] == 99
    assert call["json"]["messages"][0]["content"] == "prompt"


# ── ai_agent seam integration (Ollama down → cloud for job-public only) ───────


def test_call_ollama_json_falls_back_to_cloud_for_classify(monkeypatch):
    import job_agent.ai_agent as ai

    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "g")

    class _DownRequests:
        @staticmethod
        def post(*args, **kwargs):
            raise ConnectionError("ollama down")

    monkeypatch.setattr(ai, "requests", _DownRequests)
    stub = _StubRequests([_Resp(_chat_payload('{"role_family": "data_science"}'))])
    monkeypatch.setattr(lp, "requests", stub)

    from job_agent.polish import PolishOptions

    result = ai._call_ollama_json("job-only prompt", PolishOptions(enabled=True), task="classify")
    assert result == {"role_family": "data_science"}
    assert len(stub.calls) == 1


def test_call_ollama_json_never_clouds_candidate_tasks(monkeypatch):
    import job_agent.ai_agent as ai

    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "g")

    class _DownRequests:
        @staticmethod
        def post(*args, **kwargs):
            raise ConnectionError("ollama down")

    monkeypatch.setattr(ai, "requests", _DownRequests)
    stub = _StubRequests([_Resp(_chat_payload('{"never": "sent"}'))])
    monkeypatch.setattr(lp, "requests", stub)

    from job_agent.polish import PolishOptions

    result = ai._call_ollama_json("candidate prompt", PolishOptions(enabled=True), task="fit_analysis")
    assert result is None
    assert stub.calls == []  # candidate data must never reach a cloud endpoint


def test_is_available_true_when_cloud_only(monkeypatch):
    import job_agent.ai_agent as ai

    monkeypatch.setenv("JOB_AGENT_USE_FREE_LLM", "1")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setattr(ai, "is_ollama_reachable", lambda options=None: False)
    assert ai.is_available() is True


def test_is_available_false_when_nothing_configured(monkeypatch):
    import job_agent.ai_agent as ai

    monkeypatch.setattr(ai, "is_ollama_reachable", lambda options=None: False)
    assert ai.is_available() is False
