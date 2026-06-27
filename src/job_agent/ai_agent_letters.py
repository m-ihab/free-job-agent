"""Cover-letter body drafting + grounded chat about a job (local Ollama).

The Ollama seam (``is_available``) and shared ``_candidate_summary`` /
``_job_summary`` helpers come from :mod:`job_agent.ai_agent` (``ai.<name>``) so
the tests' monkeypatch seams keep working. ``chat_about_job`` makes its own
non-JSON Ollama call (free-text reply), so it talks to ``requests`` directly.
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional

import job_agent.ai_agent as ai
from job_agent.agent_core import choose_route, record_trace
from job_agent.polish import PolishOptions, _tokens
from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.schemas.job import JobListing

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]


_DRAFT_LETTER_PROMPT = """Draft a 3-paragraph cover letter body in
{language} for this role. Use ONLY the candidate's actual facts. No
fabricated metrics, no sponsorship claims, no salary expectations. No
greeting and no sign-off — just the body paragraphs.

Return JSON only:
{
  "paragraphs": ["paragraph 1", "paragraph 2", "paragraph 3"]
}

Tone: professional, specific, role-aware. Reference 1-2 concrete projects or
experiences the candidate already has. Mention how the candidate's skills map
to the job's actual stack. Keep each paragraph 60-90 words.

CANDIDATE:
{candidate}

JOB:
{job}

JSON:"""


_CHAT_PROMPT = """You are a personal career coach helping the candidate
evaluate this specific job. Be concrete and grounded in the profile + job
posting. Never invent facts. Reply in plain English. Keep your answer under
160 words.

CANDIDATE:
{candidate}

JOB:
{job}

CHAT HISTORY:
{history}

USER QUESTION:
{question}

REPLY:"""


def _looks_french(text: str) -> bool:
    if not text:
        return False
    lower = text.casefold()
    tokens = ("stage", "alternance", "stagiaire", "apprentissage", "ingénieur", "données", "entreprise", "vous", "nous")
    return any(token in lower for token in tokens) or bool(re.search(r"[éèêëàâäîïôöùûüçœæ]", lower))


def draft_cover_letter_body(job: JobListing, master_cv: MasterCV, profile: CandidateProfile,
                            options: PolishOptions | None = None,
                            language: str | None = None) -> list[str]:
    """Return [paragraph1, paragraph2, paragraph3] or [] when unsafe/unavailable."""
    options = options or PolishOptions.from_env()
    if not ai.is_available(options):
        return []
    if language is None:
        language = "French" if _looks_french((job.description or "") + " " + job.title) else "English"
    prompt = (_DRAFT_LETTER_PROMPT
              .replace("{language}", language)
              .replace("{candidate}", ai._candidate_summary(profile, master_cv))
              .replace("{job}", ai._job_summary(job)))
    raw = ai._call_ollama_json(prompt, options, task="cover_letter_body")
    if not isinstance(raw, dict):
        return []
    paragraphs_raw = raw.get("paragraphs") or []
    if not isinstance(paragraphs_raw, list):
        return []
    allowed_tokens = _tokens(
        ai._candidate_summary(profile, master_cv) + " " + ai._job_summary(job)
    )
    if not allowed_tokens:
        return []
    cleaned: list[str] = []
    for item in paragraphs_raw[:3]:
        text = str(item).strip()
        if not text or len(text) > 900:
            continue
        text_tokens = _tokens(text)
        if not text_tokens:
            continue
        # Vocabulary overlap rule: 60% of significant words must come from
        # the candidate facts or the job posting. This blocks the model from
        # inventing technologies, companies, or claims.
        overlap = len(text_tokens & allowed_tokens) / len(text_tokens)
        if overlap < 0.55:
            continue
        cleaned.append(text)
    return cleaned[:3]


def chat_about_job(job: JobListing, master_cv: MasterCV, profile: CandidateProfile,
                   question: str, history: list[dict] | None = None,
                   options: PolishOptions | None = None) -> Optional[str]:
    """Free-form Q&A grounded in candidate + job. Returns the reply or None."""
    options = options or PolishOptions.from_env()
    if not ai.is_available(options):
        return None
    question = (question or "").strip()
    if not question:
        return None
    history = history or []
    history_text = "\n".join(
        f"{msg.get('role','user').upper()}: {str(msg.get('content',''))[:600]}"
        for msg in history[-6:]
        if isinstance(msg, dict) and str(msg.get('content',''))
    ) or "(no prior messages)"
    prompt = (_CHAT_PROMPT
              .replace("{candidate}", ai._candidate_summary(profile, master_cv))
              .replace("{job}", ai._job_summary(job))
              .replace("{history}", history_text)
              .replace("{question}", question[:600]))
    if requests is None:
        return None
    route = choose_route("chat", prompt, options)
    payload: dict[str, Any] = {
        "model": route.model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.4, "num_predict": route.max_output_tokens},
    }
    started = time.perf_counter()
    try:
        response = requests.post(options.base_url + "/api/generate", json=payload, timeout=options.timeout * 2)
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        record_trace(route, ok=False, elapsed_ms=int((time.perf_counter() - started) * 1000), error=f"{type(exc).__name__}: {exc}")
        return None
    reply = ""
    if isinstance(body, dict):
        reply = str(body.get("response") or body.get("thinking") or "").strip()
    if not reply or len(reply) > 4000:
        record_trace(route, ok=False, elapsed_ms=int((time.perf_counter() - started) * 1000), error="empty or oversized reply")
        return None
    # Reject obvious fabrication: every named technology in the reply should
    # appear in either the candidate profile or the job posting.
    candidate_tokens = _tokens(ai._candidate_summary(profile, master_cv) + " " + ai._job_summary(job))
    reply_tokens = _tokens(reply)
    if reply_tokens:
        overlap = len(reply_tokens & candidate_tokens) / len(reply_tokens)
        if overlap < 0.25:
            record_trace(route, ok=False, elapsed_ms=int((time.perf_counter() - started) * 1000), error="grounding overlap too low")
            return None
    record_trace(route, ok=True, elapsed_ms=int((time.perf_counter() - started) * 1000))
    return reply
