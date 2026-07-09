"""Free-tier cloud LLM fallback router — job-public data only.

Adds resilience/quality to local Ollama by falling back to *free-tier*
OpenAI-compatible endpoints (Groq, Mistral La Plateforme, Cerebras, Google AI
Studio). This never becomes a paid dependency: no key → no provider → the
router returns ``None`` and callers degrade exactly as before.

Privacy contract (hard rule, mirrors CLAUDE.md):
  * Only prompts built EXCLUSIVELY from public job-posting text may leave the
    machine. The allowlist below (``JOB_PUBLIC_TASKS``) is the enforcement
    point — a task not on it is never sent to any cloud endpoint.
  * Candidate data (profile, CV, evidence, letters, chat) stays local-only.
  * Free tiers may train on inputs (e.g. Mistral's Experiment plan opt-in), so
    the allowlist must remain job-public even if a new task "seems fine".

Opt-in: set ``JOB_AGENT_USE_FREE_LLM=1`` and at least one provider key.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

try:
    import requests  # patched in tests like free_apis.requests / ai.requests
except Exception:  # pragma: no cover - requests is in install_requires
    requests = None  # type: ignore[assignment]

from job_agent.agent_core import AgentRoute, estimate_tokens, record_trace

logger = logging.getLogger(__name__)

# Tasks whose prompts are built ONLY from public job text (see ai_agent_classify:
# both prompts embed ``_job_summary(job)`` and nothing else). Extending this set
# requires re-auditing the prompt builders for candidate data.
JOB_PUBLIC_TASKS = frozenset({"classify", "summarize"})

DEFAULT_ORDER = "groq,mistral,cerebras,gemini"
DEFAULT_TIMEOUT = 30


@dataclass(frozen=True)
class CloudProvider:
    """One OpenAI-compatible free-tier chat endpoint."""

    name: str
    base_url: str  # root ending in /v1 (no trailing slash)
    env_key: str
    default_model: str

    def api_key(self) -> str:
        return os.environ.get(self.env_key, "").strip()

    def model(self) -> str:
        override = os.environ.get(f"JOB_AGENT_FREE_LLM_MODEL_{self.name.upper()}", "").strip()
        return override or self.default_model

    def chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"


PROVIDERS: dict[str, CloudProvider] = {
    "groq": CloudProvider("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"),
    "mistral": CloudProvider("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-latest"),
    "cerebras": CloudProvider("cerebras", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "gpt-oss-120b"),
    "gemini": CloudProvider(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        "gemma-3-27b-it",
    ),
}


def is_job_public_task(task: str) -> bool:
    """True when the task's prompt is built only from public job text."""
    return (task or "").strip().lower() in JOB_PUBLIC_TASKS


def enabled() -> bool:
    """Master opt-in switch, same convention as ``JOB_AGENT_USE_OLLAMA``."""
    return os.environ.get("JOB_AGENT_USE_FREE_LLM", "").strip().lower() in {"1", "true", "yes", "on"}


def provider_order() -> list[str]:
    raw = os.environ.get("JOB_AGENT_FREE_LLM_ORDER", DEFAULT_ORDER)
    return [name.strip().lower() for name in raw.split(",") if name.strip()]


def available_cloud_providers() -> list[CloudProvider]:
    """Providers that are configured (key present), in fallback order."""
    result: list[CloudProvider] = []
    for name in provider_order():
        provider = PROVIDERS.get(name)
        if provider is not None and provider.api_key():
            result.append(provider)
    return result


def cloud_enabled() -> bool:
    """True when the opt-in flag is set and at least one provider has a key."""
    return enabled() and bool(available_cloud_providers())


def _timeout() -> int:
    try:
        return int(os.environ.get("JOB_AGENT_FREE_LLM_TIMEOUT", str(DEFAULT_TIMEOUT)))
    except ValueError:
        return DEFAULT_TIMEOUT


def _parse_json(text: str) -> Optional[dict]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _post_chat(provider: CloudProvider, prompt: str, max_output_tokens: int) -> Optional[str]:
    """One chat-completions call. Returns raw content text or None."""
    if requests is None:
        return None
    payload = {
        "model": provider.model(),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": max_output_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {provider.api_key()}", "Content-Type": "application/json"}
    response = requests.post(provider.chat_url(), json=payload, headers=headers, timeout=_timeout())
    response.raise_for_status()
    body = response.json()
    choices = body.get("choices") or []
    if not choices:
        return None
    return (choices[0].get("message") or {}).get("content") or ""


def maybe_cloud_json(prompt: str, *, task: str, max_output_tokens: int = 512) -> Optional[dict]:
    """Try the free-tier chain for a job-public task. None on any refusal/failure.

    Silent-by-design like the Ollama path: callers already treat ``None`` as
    "AI unavailable" and fall back deterministically.
    """
    if not enabled() or not is_job_public_task(task):
        return None
    for provider in available_cloud_providers():
        route = AgentRoute(
            task=task,
            tier="L2",
            model=f"cloud:{provider.name}/{provider.model()}",
            reason="free-tier cloud fallback (job-public task)",
            estimated_input_tokens=estimate_tokens(prompt),
            max_output_tokens=max_output_tokens,
        )
        started = time.perf_counter()
        try:
            content = _post_chat(provider, prompt, max_output_tokens)
        except Exception as exc:
            record_trace(route, ok=False, elapsed_ms=int((time.perf_counter() - started) * 1000),
                         error=f"{type(exc).__name__}: {exc}")
            logger.info("free-LLM provider %s failed (%s); trying next", provider.name, type(exc).__name__)
            continue
        parsed = _parse_json(content or "")
        record_trace(route, ok=parsed is not None,
                     elapsed_ms=int((time.perf_counter() - started) * 1000),
                     error="" if parsed is not None else "invalid or empty json")
        if parsed is not None:
            return parsed
    return None
