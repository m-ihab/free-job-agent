"""Optional local LLM polishing for tailored CV bullets and cover letters.

This module talks to a locally-running Ollama server (``http://127.0.0.1:11434``
by default) to lightly polish text while enforcing strict safety rules:

- The original facts must remain present in the polished output (no fabrication).
- The polished text cannot grow beyond a small ratio (default 1.4x).
- A bag-of-tokens overlap check rejects responses that drift too far from the
  source.
- Numbers in the source are preserved verbatim.

The feature is opt-in: callers must explicitly set ``JOB_AGENT_USE_OLLAMA=1`` or
pass ``enabled=True``. When Ollama is not reachable, the original text is
returned unchanged — the pipeline never depends on the LLM being available.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable

try:
    import requests
except Exception:  # pragma: no cover - requests is in install_requires
    requests = None  # type: ignore[assignment]


DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.2:3b"
DEFAULT_TIMEOUT = 45

_PREFERRED_MODELS = [
    "qwen3.6:latest",
    "qwen3:latest",
    "qwen2.5:latest",
    "llama3.2:3b",
    "llama3.2:latest",
    "mistral:latest",
    "gemma3:latest",
]


@dataclass(frozen=True)
class PolishOptions:
    enabled: bool = False
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: int = DEFAULT_TIMEOUT
    max_length_ratio: float = 1.4
    min_token_overlap: float = 0.55

    @classmethod
    def from_env(cls) -> "PolishOptions":
        return cls(
            enabled=os.environ.get("JOB_AGENT_USE_OLLAMA", "").strip() in {"1", "true", "yes", "on"},
            base_url=os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            model=os.environ.get("JOB_AGENT_OLLAMA_MODEL", DEFAULT_MODEL),
            timeout=int(os.environ.get("JOB_AGENT_OLLAMA_TIMEOUT", str(DEFAULT_TIMEOUT))),
            max_length_ratio=float(os.environ.get("JOB_AGENT_OLLAMA_MAX_RATIO", "1.4")),
            min_token_overlap=float(os.environ.get("JOB_AGENT_OLLAMA_MIN_OVERLAP", "0.55")),
        )


_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9'\-]+")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _tokens(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN_RE.finditer(text)}


def _numbers(text: str) -> set[str]:
    return {match.group(0) for match in _NUMBER_RE.finditer(text)}


def available_ollama_models(options: PolishOptions | None = None) -> list[str]:
    """Return local Ollama model names, or [] if the server is unavailable."""
    options = options or PolishOptions.from_env()
    if requests is None:
        return []
    try:
        response = requests.get(options.base_url + "/api/tags", timeout=options.timeout)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    models = data.get("models", []) if isinstance(data, dict) else []
    names: list[str] = []
    for item in models:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("model") or "").strip()
            if name:
                names.append(name)
    return names


def resolve_ollama_model(options: PolishOptions | None = None) -> str:
    """Pick the best installed Ollama model for this machine.

    The app used to default to llama3.2:3b. On machines where a different local
    model is installed, such as qwen3.6:latest, that caused silent AI failures.
    This resolver keeps explicit env config first, then picks a known good
    local model, then falls back to the first installed model.
    """
    options = options or PolishOptions.from_env()
    requested = (options.model or "").strip()
    models = available_ollama_models(options)
    if not models:
        return requested or DEFAULT_MODEL
    if requested in models:
        return requested
    requested_family = requested.split(":", 1)[0] if requested else ""
    if requested_family:
        for model in models:
            if model.split(":", 1)[0] == requested_family:
                return model
    for preferred in _PREFERRED_MODELS:
        if preferred in models:
            return preferred
    for preferred in _PREFERRED_MODELS:
        preferred_family = preferred.split(":", 1)[0]
        for model in models:
            if model.split(":", 1)[0] == preferred_family:
                return model
    return models[0]


def is_ollama_reachable(options: PolishOptions | None = None) -> bool:
    """Return True when a local Ollama server responds, regardless of opt-in."""
    return bool(available_ollama_models(options or PolishOptions.from_env()))


def ollama_status(options: PolishOptions | None = None) -> dict:
    """Small readiness payload for CLI/UI diagnostics."""
    options = options or PolishOptions.from_env()
    models = available_ollama_models(options)
    selected = resolve_ollama_model(options) if models else options.model
    return {
        "enabled": options.enabled,
        "reachable": bool(models),
        "ready": bool(models),
        "selected_model": selected,
        "models": models,
        "base_url": options.base_url,
    }


def _ollama_available(options: PolishOptions, *, require_enabled: bool = True) -> bool:
    if require_enabled and not options.enabled:
        return False
    return is_ollama_reachable(options)


def _call_ollama(prompt: str, options: PolishOptions) -> str | None:
    if requests is None:
        return None
    payload = {
        "model": resolve_ollama_model(options),
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 512},
    }
    try:
        response = requests.post(options.base_url + "/api/generate", json=payload, timeout=options.timeout)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None
    text = data.get("response", "") if isinstance(data, dict) else ""
    return text.strip() if isinstance(text, str) else None


def _is_safe_rewrite(original: str, candidate: str, options: PolishOptions) -> bool:
    if not candidate or candidate == original:
        return False
    if len(candidate) > len(original) * options.max_length_ratio:
        return False
    original_tokens = _tokens(original)
    candidate_tokens = _tokens(candidate)
    if not original_tokens:
        return False
    overlap = len(original_tokens & candidate_tokens) / len(original_tokens)
    if overlap < options.min_token_overlap:
        return False
    # Numbers must match exactly: keep every original number, and no new ones.
    original_numbers = _numbers(original)
    candidate_numbers = _numbers(candidate)
    if original_numbers != candidate_numbers:
        return False
    return True


_BULLET_PROMPT = (
    "You are an expert technical recruiter polishing CV bullet points for a "
    "data science / machine learning candidate applying to a French employer. "
    "Rewrite the bullet point below in concise, professional English. "
    "Strict rules: keep every fact, number, technology name, company, and date "
    "from the original. Do not invent new facts. Do not add metrics that are "
    "not already present. Keep it under 30 words. Reply with the rewritten "
    "bullet only, no extra commentary.\n\nOriginal:\n{bullet}\n\nRewritten:"
)


def polish_bullet(bullet: str, options: PolishOptions | None = None) -> str:
    """Optionally polish a single bullet. Returns the original on any failure."""
    options = options or PolishOptions.from_env()
    if not _ollama_available(options):
        return bullet
    candidate = _call_ollama(_BULLET_PROMPT.format(bullet=bullet.strip()), options)
    if candidate is None:
        return bullet
    candidate = candidate.strip().strip('"').strip("'")
    # Trim leading bullet glyphs that some models add.
    candidate = re.sub(r"^[-*•·\s]+", "", candidate).strip()
    if not _is_safe_rewrite(bullet, candidate, options):
        return bullet
    return candidate


def polish_bullets(bullets: Iterable[str], options: PolishOptions | None = None) -> list[str]:
    options = options or PolishOptions.from_env()
    if not options.enabled:
        return list(bullets)
    return [polish_bullet(bullet, options) for bullet in bullets]


_LETTER_PROMPT = (
    "You are polishing the body of a cover letter for a French employer. "
    "Rewrite the paragraph below to read fluently and professionally in the "
    "original language. Strict rules: do not invent any new facts, do not add "
    "metrics, dates, sponsorship claims, or salary expectations. Keep every "
    "company, role, technology, and number from the original. Do not add a "
    "greeting or sign-off. Reply with the rewritten paragraph only.\n\n"
    "Original:\n{paragraph}\n\nRewritten:"
)


def polish_paragraph(paragraph: str, options: PolishOptions | None = None) -> str:
    options = options or PolishOptions.from_env()
    if not _ollama_available(options):
        return paragraph
    candidate = _call_ollama(_LETTER_PROMPT.format(paragraph=paragraph.strip()), options)
    if candidate is None:
        return paragraph
    candidate = candidate.strip().strip('"').strip("'")
    if not _is_safe_rewrite(paragraph, candidate, options):
        return paragraph
    return candidate


def is_ollama_enabled_and_reachable(options: PolishOptions | None = None) -> bool:
    """Convenience for the UI / readiness panel."""
    return _ollama_available(options or PolishOptions.from_env())
