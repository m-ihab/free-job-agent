"""Local-Ollama AI helpers for grounded job analysis and generation (facade).

Everything here runs against a local Ollama server when one is reachable; each
function degrades safely (returns ``None``/``[]``/deterministic fallback) when
it is not. Nothing is ever sent to a paid API. Job-public tasks (classify /
summarize — prompts built only from public job text) may additionally fall back
to opt-in *free-tier* cloud endpoints via :mod:`job_agent.llm_providers`;
candidate data never leaves the machine.

This module keeps the shared primitives — the Ollama JSON call, availability
probe, and the candidate/job prompt summaries — and re-exports the task-specific
helpers from sibling modules so the file stays small:
  * :mod:`job_agent.ai_agent_fit` — fit analysis, tailored summary, cover bullets
  * :mod:`job_agent.ai_agent_classify` — job classification + TL;DR
  * :mod:`job_agent.ai_agent_letters` — cover-letter body + grounded chat
  * :mod:`job_agent.ai_agent_search` — AI search-query planning

The sibling modules reach ``is_available`` / ``_call_ollama_json`` and the
summary helpers as ``ai_agent.<name>`` (call-time attribute lookup), so the
ai_agent tests' ``monkeypatch.setattr(ai_agent, ...)`` seams keep working.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from job_agent.polish import (  # noqa: F401  (PolishOptions re-exported for callers)
    PolishOptions,
    _tokens,
    is_ollama_reachable,
    resolve_ollama_model,
)
from job_agent.agent_core import choose_route, record_trace
from job_agent import llm_providers
from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.schemas.job import JobListing


@dataclass
class FitAnalysis:
    """Structured fit-analysis output the LLM produces."""

    verdict: str           # one of: strong, moderate, weak
    score: int             # 0–100
    strengths: list[str]
    gaps: list[str]
    suggested_emphasis: list[str]
    summary: str
    confidence: float      # 0–1

    @classmethod
    def from_dict(cls, raw: dict) -> Optional["FitAnalysis"]:
        try:
            verdict = str(raw.get("verdict") or "").strip().lower()
            if verdict not in {"strong", "moderate", "weak"}:
                return None
            score = int(round(float(raw.get("score") or 0)))
            score = max(0, min(100, score))
            strengths = [str(item).strip() for item in raw.get("strengths", []) if str(item).strip()][:6]
            gaps = [str(item).strip() for item in raw.get("gaps", []) if str(item).strip()][:6]
            suggested = [str(item).strip() for item in raw.get("suggested_emphasis", []) if str(item).strip()][:8]
            summary = str(raw.get("summary") or "").strip()
            confidence = float(raw.get("confidence") or 0.5)
            confidence = max(0.0, min(1.0, confidence))
            if not summary or len(summary) > 800:
                return None
            return cls(verdict=verdict, score=score, strengths=strengths, gaps=gaps,
                       suggested_emphasis=suggested, summary=summary, confidence=confidence)
        except Exception:
            return None

    def to_dict(self) -> dict:
        return asdict(self)


def is_available(options: PolishOptions | None = None) -> bool:
    """Return True if a local Ollama server is reachable.

    AI fit analysis and search planning are local-only and safe to auto-enable
    when Ollama is running. Text polishing remains separately opt-in in
    ``polish.py`` because it rewrites user-facing prose.

    Also True when the opt-in free-tier cloud fallback is configured: job-public
    tasks (classify/summarize) can then run cloud-only, while candidate-data
    tasks still no-op safely when Ollama itself is down.
    """
    options = options or PolishOptions.from_env()
    return is_ollama_reachable(options) or llm_providers.cloud_enabled()


def _call_ollama_json(prompt: str, options: PolishOptions, *, task: str = "general") -> Optional[dict]:
    """Call Ollama and parse the response as JSON. Returns None on failure.

    On Ollama failure, job-public tasks may fall back to the opt-in free-tier
    cloud chain (see :mod:`job_agent.llm_providers`); it returns ``None`` for
    every other task, so the signature and degrade semantics stay unchanged.
    """
    route = choose_route(task, prompt, options)
    if requests is None:
        return llm_providers.maybe_cloud_json(prompt, task=task, max_output_tokens=route.max_output_tokens)
    payload: dict[str, Any] = {
        "model": route.model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_predict": route.max_output_tokens},
    }
    started = time.perf_counter()
    try:
        response = requests.post(options.base_url + "/api/generate", json=payload, timeout=options.timeout * 2)
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        record_trace(route, ok=False, elapsed_ms=int((time.perf_counter() - started) * 1000), error=f"{type(exc).__name__}: {exc}")
        return llm_providers.maybe_cloud_json(prompt, task=task, max_output_tokens=route.max_output_tokens)
    raw_text = ""
    if isinstance(body, dict):
        raw_text = body.get("response", "") or body.get("thinking", "")
    if not raw_text:
        record_trace(route, ok=False, elapsed_ms=int((time.perf_counter() - started) * 1000), error="empty response")
        return llm_providers.maybe_cloud_json(prompt, task=task, max_output_tokens=route.max_output_tokens)
    # Some models return text with code fences around JSON; strip them.
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        record_trace(route, ok=isinstance(parsed, dict), elapsed_ms=int((time.perf_counter() - started) * 1000))
        return parsed
    except Exception as exc:
        record_trace(route, ok=False, elapsed_ms=int((time.perf_counter() - started) * 1000), error=f"invalid json: {exc}")
        return llm_providers.maybe_cloud_json(prompt, task=task, max_output_tokens=route.max_output_tokens)


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _candidate_summary(profile: CandidateProfile, master_cv: MasterCV) -> str:
    skills = [s.name for s in master_cv.skills][:25]
    experiences = []
    for exp in master_cv.experience[:4]:
        experiences.append(f"- {exp.title} at {exp.company} ({exp.start_date or ''}–{exp.end_date or 'Present'})")
    projects = [p.name for p in master_cv.projects[:5]]
    summary = profile.summary or master_cv.summary or ""
    return (
        f"Name: {master_cv.contact.name}\n"
        f"Summary: {_truncate(summary, 400)}\n"
        f"Skills: {', '.join(skills)}\n"
        f"Experience:\n" + "\n".join(experiences) + "\n"
        f"Projects: {', '.join(projects)}\n"
        f"Languages: {', '.join(profile.languages)}"
    )


def _job_summary(job: JobListing) -> str:
    return (
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location or ''}\n"
        f"Type: {job.job_type or ''}\n"
        f"Remote: {job.remote}\n"
        f"Tech: {', '.join(job.tech_stack[:25])}\n"
        f"Requirements: {', '.join(job.requirements[:12])}\n"
        f"Description: {_truncate(job.description or '', 1600)}"
    )


# Task-specific helpers live in sibling modules; re-export so existing imports
# (``from job_agent.ai_agent import analyze_fit, ...``) keep working unchanged.
from job_agent.ai_agent_fit import (  # noqa: E402,F401  (re-export; after primitives to avoid cycle)
    analyze_fit,
    generate_cover_letter_bullets,
    generate_tailored_summary,
)
from job_agent.ai_agent_classify import classify_job, summarize_job  # noqa: E402,F401  (re-export)
from job_agent.ai_agent_letters import (  # noqa: E402,F401  (re-export)
    _looks_french,
    chat_about_job,
    draft_cover_letter_body,
)
from job_agent.ai_agent_search import _clean_query, suggest_search_queries  # noqa: E402,F401  (re-export)

__all__ = [
    "FitAnalysis",
    "is_available",
    "analyze_fit",
    "generate_tailored_summary",
    "generate_cover_letter_bullets",
    "classify_job",
    "summarize_job",
    "draft_cover_letter_body",
    "chat_about_job",
    "suggest_search_queries",
]
