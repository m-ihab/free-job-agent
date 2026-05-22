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

import json
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
DEFAULT_TIMEOUT = 20


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


def _ollama_available(options: PolishOptions) -> bool:
    if not options.enabled or requests is None:
        return False
    try:
        response = requests.get(options.base_url + "/api/tags", timeout=options.timeout)
        return response.status_code == 200
    except Exception:
        return False


def _call_ollama(prompt: str, options: PolishOptions) -> str | None:
    if requests is None:
        return None
    payload = {
        "model": options.model,
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
