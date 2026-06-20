"""Tests for AI trace telemetry read/summary.

Covers the read/aggregate layer over agent_core's per-call routing telemetry
that the UI reads, without exposing prompts.
"""
from __future__ import annotations

import json

import job_agent.agent_core as ac
from job_agent.agent_core import AgentRoute, read_traces, record_trace, trace_summary


def _route(task="chat", tier="L2", model="m"):
    return AgentRoute(
        task=task, tier=tier, model=model, reason="t",
        estimated_input_tokens=10, max_output_tokens=128,
    )


def test_read_traces_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "trace_path", lambda: tmp_path / "ai_traces.jsonl")
    assert read_traces() == []


def test_record_then_read_is_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "trace_path", lambda: tmp_path / "ai_traces.jsonl")
    record_trace(_route(task="first"), ok=True, elapsed_ms=100)
    record_trace(_route(task="second"), ok=False, elapsed_ms=200, error="boom")
    traces = read_traces()
    assert [t["task"] for t in traces] == ["second", "first"]
    assert traces[0]["error"] == "boom"


def test_trace_summary_aggregates_by_tier(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "trace_path", lambda: tmp_path / "ai_traces.jsonl")
    record_trace(_route(tier="L1"), ok=True, elapsed_ms=50)
    record_trace(_route(tier="L3"), ok=True, elapsed_ms=300)
    record_trace(_route(tier="L3"), ok=False, elapsed_ms=100)

    summary = trace_summary()

    assert summary["total"] == 3
    assert summary["tiers"]["L1"]["count"] == 1
    assert summary["tiers"]["L3"]["count"] == 2
    assert summary["tiers"]["L3"]["success_rate"] == 0.5
    assert summary["tiers"]["L3"]["avg_ms"] == 200
    assert round(summary["success_rate"], 3) == round(2 / 3, 3)


def test_read_traces_skips_corrupt_lines(tmp_path, monkeypatch):
    path = tmp_path / "ai_traces.jsonl"
    path.write_text(
        json.dumps({"task": "ok", "tier": "L2", "elapsed_ms": 10, "ok": True}) + "\n"
        + "not json at all\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ac, "trace_path", lambda: path)
    traces = read_traces()
    assert len(traces) == 1
    assert traces[0]["task"] == "ok"
