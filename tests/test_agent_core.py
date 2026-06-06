from __future__ import annotations

import json

from job_agent.agent_core import choose_route, estimate_tokens, record_trace, trace_path
from job_agent.polish import PolishOptions


def test_agent_core_routes_chat_to_fast_model(monkeypatch):
    monkeypatch.setattr("job_agent.agent_core.resolve_fast_model", lambda options: "llama3.2:3b")

    route = choose_route("chat", "Should I apply to this data analyst internship?", PolishOptions())

    assert route.tier == "L1"
    assert route.model == "llama3.2:3b"
    assert route.max_output_tokens == 512


def test_agent_core_routes_fit_analysis_to_heavy_model(monkeypatch):
    monkeypatch.setattr("job_agent.agent_core.resolve_ollama_model", lambda options: "qwen3.6:latest")

    route = choose_route("fit_analysis", "job " * 500, PolishOptions())

    assert route.tier == "L3"
    assert route.model == "qwen3.6:latest"


def test_agent_core_trace_is_prompt_free(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("job_agent.agent_core.resolve_fast_model", lambda options: "tiny")
    route = choose_route("summarize", "very secret prompt text", PolishOptions(fast_model="tiny"))

    record_trace(route, ok=True, elapsed_ms=12)

    lines = trace_path().read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[-1])
    assert payload["task"] == "summarize"
    assert payload["ok"] is True
    assert "very secret prompt text" not in lines[-1]


def test_estimate_tokens_is_never_zero():
    assert estimate_tokens("") == 1
