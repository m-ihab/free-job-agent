"""Behavioural tests for the optional local-AI agent.

These tests never touch a real Ollama server. The single LLM transport
function ``_call_ollama_json`` (and the raw ``requests.post`` path used by
``chat_about_job``) is monkeypatched so we can exercise the deterministic
parsing / validation / fallback branches in isolation.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import job_agent.ai_agent as ai
from job_agent.ai_agent import FitAnalysis
from job_agent.polish import PolishOptions


# ── Helpers ───────────────────────────────────────────────────────────────────


def _opts() -> PolishOptions:
    return PolishOptions(enabled=True, base_url="http://127.0.0.1:11434")


@pytest.fixture
def available(monkeypatch):
    """Force is_available() True without a real server."""
    monkeypatch.setattr(ai, "is_available", lambda options=None: True)


@pytest.fixture
def unavailable(monkeypatch):
    monkeypatch.setattr(ai, "is_available", lambda options=None: False)


def _patch_llm(monkeypatch, payload):
    """Replace the JSON transport with a canned return value."""
    monkeypatch.setattr(ai, "_call_ollama_json", lambda prompt, options, *, task="general": payload)


# ── FitAnalysis.from_dict (pure parsing / validation) ─────────────────────────


def test_fit_analysis_from_dict_parses_valid_payload():
    raw = {
        "verdict": "Strong",
        "score": 88,
        "strengths": ["Python", "  ", "Pandas"],
        "gaps": ["No Spark"],
        "suggested_emphasis": ["MLOps"],
        "summary": "A solid match for the role.",
        "confidence": 0.9,
    }

    fit = FitAnalysis.from_dict(raw)

    assert fit is not None
    assert fit.verdict == "strong"  # lowercased
    assert fit.score == 88
    assert fit.strengths == ["Python", "Pandas"]  # blank entry dropped
    assert fit.confidence == 0.9


def test_fit_analysis_clamps_score_and_confidence():
    fit = FitAnalysis.from_dict(
        {"verdict": "moderate", "score": 250, "summary": "ok", "confidence": 5.0}
    )

    assert fit is not None
    assert fit.score == 100  # clamped to 0..100
    assert fit.confidence == 1.0  # clamped to 0..1


def test_fit_analysis_rejects_unknown_verdict():
    assert FitAnalysis.from_dict({"verdict": "amazing", "score": 50, "summary": "x"}) is None


def test_fit_analysis_rejects_empty_summary():
    assert FitAnalysis.from_dict({"verdict": "weak", "score": 10, "summary": "   "}) is None


def test_fit_analysis_rejects_oversized_summary():
    assert FitAnalysis.from_dict(
        {"verdict": "weak", "score": 10, "summary": "x" * 801}
    ) is None


# ── analyze_fit ───────────────────────────────────────────────────────────────


def test_analyze_fit_returns_none_when_ai_unavailable(unavailable, sample_job, sample_master_cv, sample_profile):
    assert ai.analyze_fit(sample_job, sample_master_cv, sample_profile, _opts()) is None


def test_analyze_fit_returns_structured_object(available, monkeypatch, sample_job, sample_master_cv, sample_profile):
    _patch_llm(monkeypatch, {
        "verdict": "moderate", "score": 70,
        "strengths": ["python"], "gaps": [], "suggested_emphasis": [],
        "summary": "Reasonable fit.", "confidence": 0.6,
    })

    fit = ai.analyze_fit(sample_job, sample_master_cv, sample_profile, _opts())

    assert isinstance(fit, FitAnalysis)
    assert fit.verdict == "moderate"


def test_analyze_fit_discards_non_dict_response(available, monkeypatch, sample_job, sample_master_cv, sample_profile):
    _patch_llm(monkeypatch, ["not", "a", "dict"])
    assert ai.analyze_fit(sample_job, sample_master_cv, sample_profile, _opts()) is None


# ── generate_tailored_summary (token-overlap grounding) ───────────────────────


def test_tailored_summary_rejected_when_vocabulary_unrelated(available, monkeypatch, sample_job, sample_master_cv, sample_profile):
    # The summary shares no vocabulary with the candidate base summary or the job.
    _patch_llm(monkeypatch, {"summary": "Zzzz qqqq wwww vvvv yyyy uuuu oooo"})

    result = ai.generate_tailored_summary(sample_job, sample_master_cv, sample_profile, _opts())

    assert result is None


def test_tailored_summary_accepted_when_grounded_in_job(available, monkeypatch, sample_job, sample_master_cv, sample_profile):
    # Echo job tech-stack vocabulary so overlap-with-job clears the threshold.
    grounded = " ".join(sample_job.tech_stack + sample_job.requirements + [sample_job.title])
    _patch_llm(monkeypatch, {"summary": grounded})

    result = ai.generate_tailored_summary(sample_job, sample_master_cv, sample_profile, _opts())

    assert result == grounded


def test_tailored_summary_rejected_when_empty(available, monkeypatch, sample_job, sample_master_cv, sample_profile):
    _patch_llm(monkeypatch, {"summary": "   "})
    assert ai.generate_tailored_summary(sample_job, sample_master_cv, sample_profile, _opts()) is None


# ── generate_cover_letter_bullets ─────────────────────────────────────────────


def test_cover_bullets_empty_when_unavailable(unavailable, sample_job, sample_master_cv, sample_profile):
    assert ai.generate_cover_letter_bullets(sample_job, sample_master_cv, sample_profile, _opts()) == []


def test_cover_bullets_filters_hallucinated_text(available, monkeypatch, sample_job, sample_master_cv, sample_profile):
    grounded = " ".join(sample_job.tech_stack + sample_job.requirements)
    _patch_llm(monkeypatch, {"bullets": [
        grounded,  # fully grounded -> kept
        "Quantum blockchain synergy unicorn rocketship wizardry",  # hallucinated -> dropped
    ]})

    bullets = ai.generate_cover_letter_bullets(sample_job, sample_master_cv, sample_profile, _opts())

    assert grounded in bullets
    assert all("unicorn" not in b for b in bullets)


def test_cover_bullets_returns_empty_for_non_list(available, monkeypatch, sample_job, sample_master_cv, sample_profile):
    _patch_llm(monkeypatch, {"bullets": "a string not a list"})
    assert ai.generate_cover_letter_bullets(sample_job, sample_master_cv, sample_profile, _opts()) == []


# ── classify_job (enum normalisation) ─────────────────────────────────────────


def test_classify_job_normalises_invalid_enums(available, monkeypatch, sample_job):
    _patch_llm(monkeypatch, {
        "role_family": "wizardry",      # invalid -> other
        "seniority": "principal",        # invalid -> ""
        "contract": "internship",        # invalid -> ""
        "remote_mode": "telepresence",   # invalid -> unknown
        "tags": ["Python", "ML"],
        "must_haves": ["x"], "nice_to_haves": ["y"],
        "language_requirements": ["English"],
    })

    result = ai.classify_job(sample_job, _opts())

    assert result["role_family"] == "other"
    assert result["seniority"] == ""
    assert result["contract"] == ""
    assert result["remote_mode"] == "unknown"
    assert result["tags"] == ["python", "ml"]  # lowercased


def test_classify_job_keeps_valid_enums(available, monkeypatch, sample_job):
    _patch_llm(monkeypatch, {
        "role_family": "data_science", "seniority": "junior",
        "contract": "stage", "remote_mode": "remote",
        "tags": [], "must_haves": [], "nice_to_haves": [], "language_requirements": [],
    })

    result = ai.classify_job(sample_job, _opts())

    assert result["role_family"] == "data_science"
    assert result["seniority"] == "junior"
    assert result["contract"] == "stage"


# ── summarize_job ─────────────────────────────────────────────────────────────


def test_summarize_job_rejects_empty_tldr(available, monkeypatch, sample_job):
    _patch_llm(monkeypatch, {"tldr": "", "key_signals": ["a"]})
    assert ai.summarize_job(sample_job, _opts()) is None


def test_summarize_job_returns_tldr_and_signals(available, monkeypatch, sample_job):
    _patch_llm(monkeypatch, {"tldr": "Two sentence summary.", "key_signals": ["remote", "python", ""]})

    result = ai.summarize_job(sample_job, _opts())

    assert result["tldr"] == "Two sentence summary."
    assert result["key_signals"] == ["remote", "python"]  # blank dropped


# ── _looks_french / _clean_query (pure helpers) ──────────────────────────────


@pytest.mark.parametrize("text, expected", [
    ("Recherche stagiaire data science", True),
    ("Ingénieur données entreprise", True),
    ("We seek a data scientist", False),
    ("", False),
])
def test_looks_french(text, expected):
    assert ai._looks_french(text) is expected


@pytest.mark.parametrize("raw, expected", [
    ('"data scientist"', "data scientist"),       # quotes stripped
    ("stage   data", "stage data"),                # whitespace collapsed
    ("https://example.com", ""),                   # URLs rejected
    ("query (with parens)", ""),                   # bracket chars rejected
    ("x" * 80, ""),                                # too long rejected
])
def test_clean_query(raw, expected):
    assert ai._clean_query(raw) == expected


# ── suggest_search_queries (deterministic fallback + AI merge) ───────────────


def test_suggest_queries_uses_fallback_when_unavailable(unavailable, sample_profile, sample_master_cv):
    result = ai.suggest_search_queries(sample_profile, sample_master_cv, options=_opts())

    assert result["used_ai"] is False
    assert result["queries"]  # deterministic expansion is non-empty
    assert "Deterministic" in result["rationale"]


def test_suggest_queries_falls_back_when_ai_returns_no_queries(available, monkeypatch, sample_profile, sample_master_cv):
    monkeypatch.setattr(ai, "resolve_ollama_model", lambda options=None: "test-model")
    _patch_llm(monkeypatch, {"queries": [], "rationale": "n/a"})

    result = ai.suggest_search_queries(sample_profile, sample_master_cv, options=_opts())

    assert result["used_ai"] is False
    assert result["queries"]


def test_suggest_queries_merges_ai_and_fallback(available, monkeypatch, sample_profile, sample_master_cv):
    monkeypatch.setattr(ai, "resolve_ollama_model", lambda options=None: "test-model")
    _patch_llm(monkeypatch, {"queries": ["stage data", "alternance ml"], "rationale": "AI plan"})

    result = ai.suggest_search_queries(
        sample_profile, sample_master_cv, seed_query="data scientist", limit=10, options=_opts()
    )

    assert result["used_ai"] is True
    assert "stage data" in result["queries"]
    assert result["model"] == "test-model"
    assert len(result["queries"]) <= 10


def test_suggest_queries_respects_limit_clamp(available, monkeypatch, sample_profile, sample_master_cv):
    monkeypatch.setattr(ai, "resolve_ollama_model", lambda options=None: "m")
    _patch_llm(monkeypatch, {"queries": [f"q{i}" for i in range(50)], "rationale": "lots"})

    result = ai.suggest_search_queries(sample_profile, sample_master_cv, limit=3, options=_opts())

    assert len(result["queries"]) == 3


# ── _call_ollama_json transport (requests mocked) ────────────────────────────


def _fake_response(json_body):
    return SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: json_body,
    )


def test_call_ollama_json_strips_code_fences(monkeypatch):
    body = {"response": '```json\n{"a": 1}\n```'}
    monkeypatch.setattr(ai, "requests", SimpleNamespace(post=lambda *a, **k: _fake_response(body)))

    parsed = ai._call_ollama_json("prompt", _opts(), task="general")

    assert parsed == {"a": 1}


def test_call_ollama_json_returns_none_on_invalid_json(monkeypatch):
    body = {"response": "this is not json"}
    monkeypatch.setattr(ai, "requests", SimpleNamespace(post=lambda *a, **k: _fake_response(body)))

    assert ai._call_ollama_json("prompt", _opts()) is None


def test_call_ollama_json_returns_none_on_empty_response(monkeypatch):
    monkeypatch.setattr(ai, "requests", SimpleNamespace(post=lambda *a, **k: _fake_response({"response": ""})))

    assert ai._call_ollama_json("prompt", _opts()) is None


def test_call_ollama_json_returns_none_when_requests_missing(monkeypatch):
    monkeypatch.setattr(ai, "requests", None)
    assert ai._call_ollama_json("prompt", _opts()) is None


def test_call_ollama_json_handles_transport_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(ai, "requests", SimpleNamespace(post=_boom))

    assert ai._call_ollama_json("prompt", _opts()) is None
