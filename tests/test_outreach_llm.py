"""Tests for the local-Ollama outreach enhancer.

The enhancer must: return None when Ollama is unreachable (so callers keep the
deterministic draft), return the model's text when it is grounded, and reject
(return None) any enhancement the honesty guard flags.
"""
from __future__ import annotations

import job_agent.ai_agent as ai_agent
from job_agent.generator import outreach_llm
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, MasterCV, Skill
from job_agent.schemas.job import JobListing

_DRAFT = "Hi! I came across Acme Analytics' Data Scientist role and I'd love to connect."


def _profile() -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name="Marie Curie", email="marie@example.com"),
        skills=[Skill(name="Python"), Skill(name="pandas")],
        target_roles=["Data Scientist"],
        target_locations=["Paris"],
        languages=["English", "French"],
    )


def _master_cv() -> MasterCV:
    return MasterCV(contact={"name": "Marie Curie", "email": "marie@example.com"},
                    skills=[{"name": "Python"}], experience=[], projects=[], education=[])


def _job() -> JobListing:
    return JobListing(title="Data Scientist", company="Acme Analytics",
                      location="Paris, France", tech_stack=["Python", "SQL"],
                      description="We need a data scientist for our Paris team.")


def _enhance(monkeypatch, *, available: bool, response):
    monkeypatch.setattr(ai_agent, "is_available", lambda *a, **k: available)
    monkeypatch.setattr(ai_agent, "_call_ollama_json", lambda *a, **k: response)
    return outreach_llm.enhance_message(
        _DRAFT, job=_job(), master_cv=_master_cv(), profile=_profile(), kind="connect",
    )


def test_returns_none_when_ollama_unavailable(monkeypatch) -> None:
    result = _enhance(monkeypatch, available=False, response={"message": "anything"})
    assert result is None


def test_returns_none_when_model_returns_nothing(monkeypatch) -> None:
    assert _enhance(monkeypatch, available=True, response=None) is None


def test_returns_grounded_enhancement(monkeypatch) -> None:
    grounded = ("Hi! I spotted the Data Scientist opening at Acme Analytics in Paris and "
                "would love to connect — my Python and pandas work lines up well.")
    result = _enhance(monkeypatch, available=True, response={"message": grounded})
    assert result == grounded


def test_rejects_enhancement_with_invented_metric(monkeypatch) -> None:
    bad = _DRAFT + " I boosted accuracy by 40% in my last role."
    result = _enhance(monkeypatch, available=True, response={"message": bad})
    assert result is None  # guard flags '40', caller falls back to the draft


def test_rejects_empty_message_field(monkeypatch) -> None:
    assert _enhance(monkeypatch, available=True, response={"message": "   "}) is None


def _select(monkeypatch, *, engine, available, response):
    monkeypatch.setattr(ai_agent, "is_available", lambda *a, **k: available)
    monkeypatch.setattr(ai_agent, "_call_ollama_json", lambda *a, **k: response)
    return outreach_llm.select_outreach_text(
        _DRAFT, job=_job(), master_cv=_master_cv(), profile=_profile(),
        kind="connect", engine=engine,
    )


def test_standard_engine_skips_ollama_even_when_available(monkeypatch) -> None:
    text, used = _select(monkeypatch, engine="standard", available=True,
                         response={"message": "Hi from Acme Analytics Data Scientist in Paris"})
    assert text == _DRAFT
    assert used == "standard"


def test_auto_engine_uses_grounded_enhancement(monkeypatch) -> None:
    grounded = "Hi! The Data Scientist role at Acme Analytics in Paris caught my eye — Python fits."
    text, used = _select(monkeypatch, engine="auto", available=True, response={"message": grounded})
    assert text == grounded
    assert used == "smart"


def test_auto_engine_falls_back_when_unavailable(monkeypatch) -> None:
    text, used = _select(monkeypatch, engine="auto", available=False, response=None)
    assert text == _DRAFT
    assert used == "standard"
