"""Safety tests for the optional Ollama polishing layer.

The point of these tests is to confirm that the polish layer never silently
breaks the pipeline and never accepts unsafe rewrites.
"""
from __future__ import annotations

from job_agent import polish
from job_agent.polish import PolishOptions, _is_safe_rewrite, polish_bullet, polish_bullets, resolve_ollama_model


def _opts() -> PolishOptions:
    return PolishOptions(enabled=False)


def test_polish_bullet_returns_original_when_disabled():
    bullet = "Built a Flask app with scikit-learn for cybersecurity attack prediction."
    assert polish_bullet(bullet, _opts()) == bullet


def test_polish_bullets_passthrough_when_disabled():
    bullets = ["a", "b", "c"]
    assert polish_bullets(bullets, _opts()) == bullets


def test_safe_rewrite_rejects_made_up_numbers():
    original = "Built a Flask app with scikit-learn for attack prediction."
    candidate = "Built a Flask app with scikit-learn that improved accuracy by 42 percent."
    assert not _is_safe_rewrite(original, candidate, PolishOptions(enabled=True))


def test_safe_rewrite_preserves_numbers():
    original = "Delivered features in 2-week Agile sprints with CI/CD pipelines."
    candidate = "Shipped features in 2-week Agile sprints with CI/CD pipelines."
    assert _is_safe_rewrite(original, candidate, PolishOptions(enabled=True))


def test_safe_rewrite_rejects_drift():
    original = "Built a Flask app with scikit-learn."
    candidate = "Wrote a poem about machine learning frameworks."
    assert not _is_safe_rewrite(original, candidate, PolishOptions(enabled=True))


def test_safe_rewrite_rejects_long_responses():
    original = "Built a Flask app."
    candidate = "Built a Flask app " * 10
    assert not _is_safe_rewrite(original, candidate, PolishOptions(enabled=True))


def test_safe_rewrite_rejects_empty_response():
    assert not _is_safe_rewrite("Something", "", PolishOptions(enabled=True))


def test_polish_options_from_env_default_disabled(monkeypatch):
    monkeypatch.delenv("JOB_AGENT_USE_OLLAMA", raising=False)
    options = PolishOptions.from_env()
    assert options.enabled is False


def test_resolve_ollama_model_prefers_installed_qwen(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "qwen3.6:latest"}]}

    class FakeRequests:
        @staticmethod
        def get(*args, **kwargs):
            return Response()

    monkeypatch.setattr(polish, "requests", FakeRequests)
    assert resolve_ollama_model(PolishOptions(model="llama3.2:3b")) == "qwen3.6:latest"


def test_resolve_ollama_model_keeps_explicit_installed_model(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "mistral:latest"}, {"name": "qwen3.6:latest"}]}

    class FakeRequests:
        @staticmethod
        def get(*args, **kwargs):
            return Response()

    monkeypatch.setattr(polish, "requests", FakeRequests)
    assert resolve_ollama_model(PolishOptions(model="mistral:latest")) == "mistral:latest"
