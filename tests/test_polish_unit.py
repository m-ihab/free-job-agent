"""Behavioural tests for job_agent.polish.

Covers PolishOptions.from_env branches, the deterministic safety checks in
_is_safe_rewrite, and the polish_* entry points with the Ollama call mocked so
no real network access occurs.
"""
from __future__ import annotations

import job_agent.polish as polish
from job_agent.polish import PolishOptions


def test_from_env_defaults_disabled_without_env(monkeypatch):
    # Arrange: clear every env var the parser reads.
    for key in [
        "JOB_AGENT_USE_OLLAMA", "OLLAMA_BASE_URL", "JOB_AGENT_OLLAMA_MODEL",
        "JOB_AGENT_OLLAMA_FAST_MODEL", "JOB_AGENT_OLLAMA_TIMEOUT",
        "JOB_AGENT_OLLAMA_MAX_RATIO", "JOB_AGENT_OLLAMA_MIN_OVERLAP",
    ]:
        monkeypatch.delenv(key, raising=False)

    # Act
    options = PolishOptions.from_env()

    # Assert: opt-in disabled, defaults applied.
    assert options.enabled is False
    assert options.base_url == polish.DEFAULT_BASE_URL
    assert options.model == polish.DEFAULT_MODEL
    assert options.timeout == polish.DEFAULT_TIMEOUT


def test_from_env_enabled_and_strips_trailing_slash(monkeypatch):
    # Arrange
    monkeypatch.setenv("JOB_AGENT_USE_OLLAMA", "yes")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example.local:9999/")
    monkeypatch.setenv("JOB_AGENT_OLLAMA_TIMEOUT", "12")
    monkeypatch.setenv("JOB_AGENT_OLLAMA_MAX_RATIO", "2.0")

    # Act
    options = PolishOptions.from_env()

    # Assert
    assert options.enabled is True
    assert options.base_url == "http://example.local:9999"  # trailing slash dropped
    assert options.timeout == 12
    assert options.max_length_ratio == 2.0


def test_from_env_treats_unknown_flag_value_as_disabled(monkeypatch):
    # Arrange
    monkeypatch.setenv("JOB_AGENT_USE_OLLAMA", "maybe")

    # Act
    options = PolishOptions.from_env()

    # Assert
    assert options.enabled is False


def test_is_safe_rewrite_rejects_identical_or_empty():
    options = PolishOptions()
    assert polish._is_safe_rewrite("Built API", "Built API", options) is False
    assert polish._is_safe_rewrite("Built API", "", options) is False


def test_is_safe_rewrite_rejects_when_numbers_change():
    # Arrange: candidate drops the "40%" number from the source.
    options = PolishOptions(min_token_overlap=0.0, max_length_ratio=5.0)
    original = "Reduced manual time by 40% across teams"
    candidate = "Reduced manual time across teams"

    # Act / Assert
    assert polish._is_safe_rewrite(original, candidate, options) is False


def test_is_safe_rewrite_rejects_low_token_overlap():
    # Arrange: high overlap requirement, totally different words.
    options = PolishOptions(min_token_overlap=0.9, max_length_ratio=5.0)

    # Act / Assert
    assert polish._is_safe_rewrite("alpha beta gamma", "delta epsilon zeta", options) is False


def test_is_safe_rewrite_accepts_faithful_paraphrase():
    # Arrange: same numbers, high overlap, similar length.
    options = PolishOptions(min_token_overlap=0.5, max_length_ratio=2.0)
    original = "Automated 15 workflows with Python and Pandas"
    candidate = "Automated 15 workflows using Python and Pandas"

    # Act / Assert
    assert polish._is_safe_rewrite(original, candidate, options) is True


def test_polish_bullet_returns_original_when_unavailable(monkeypatch):
    # Arrange: pretend Ollama is unreachable.
    monkeypatch.setattr(polish, "_ollama_available", lambda *a, **k: False)
    options = PolishOptions(enabled=True)

    # Act
    result = polish.polish_bullet("Built dashboards in Power BI", options)

    # Assert
    assert result == "Built dashboards in Power BI"


def test_polish_bullet_strips_glyphs_and_accepts_safe_rewrite(monkeypatch):
    # Arrange: a model returns a quoted, bullet-prefixed safe paraphrase.
    monkeypatch.setattr(polish, "_ollama_available", lambda *a, **k: True)
    monkeypatch.setattr(
        polish, "_call_ollama",
        lambda prompt, opts: "• Automated 15 workflows using Python",
    )
    options = PolishOptions(enabled=True, min_token_overlap=0.5, max_length_ratio=2.0)

    # Act
    result = polish.polish_bullet("Automated 15 workflows with Python", options)

    # Assert: leading bullet glyph stripped, rewrite kept.
    assert result == "Automated 15 workflows using Python"


def test_polish_bullet_falls_back_when_rewrite_unsafe(monkeypatch):
    # Arrange: model invents a new number -> rewrite must be rejected.
    monkeypatch.setattr(polish, "_ollama_available", lambda *a, **k: True)
    monkeypatch.setattr(polish, "_call_ollama", lambda prompt, opts: "Automated 99 workflows")
    options = PolishOptions(enabled=True)

    # Act
    result = polish.polish_bullet("Automated 15 workflows", options)

    # Assert
    assert result == "Automated 15 workflows"


def test_polish_bullets_returns_unchanged_when_disabled():
    # Arrange
    options = PolishOptions(enabled=False)
    bullets = ["one", "two"]

    # Act
    result = polish.polish_bullets(bullets, options)

    # Assert: a list copy of the originals, untouched.
    assert result == ["one", "two"]


def test_polish_paragraph_returns_original_when_call_returns_none(monkeypatch):
    # Arrange
    monkeypatch.setattr(polish, "_ollama_available", lambda *a, **k: True)
    monkeypatch.setattr(polish, "_call_ollama", lambda prompt, opts: None)
    options = PolishOptions(enabled=True)

    # Act
    result = polish.polish_paragraph("Motivated to join your data team.", options)

    # Assert
    assert result == "Motivated to join your data team."
