"""Job classification + TL;DR summarization (local Ollama).

The Ollama seam (``is_available`` / ``_call_ollama_json``) and the shared
``_job_summary`` helper are reached through :mod:`job_agent.ai_agent`
(``ai.<name>``) so the tests' monkeypatch seams keep working.
"""
from __future__ import annotations

from typing import Optional

import job_agent.ai_agent as ai
from job_agent.polish import PolishOptions
from job_agent.schemas.job import JobListing

_CLASSIFY_PROMPT = """You classify a job posting for a France/Paris-focused
data science candidate's tracking system. Return JSON only.

{
  "role_family": "data_science|machine_learning|data_engineering|data_analyst|software|other",
  "seniority": "intern|junior|mid|senior|lead",
  "contract": "stage|alternance|cdi|cdd|freelance|other",
  "remote_mode": "remote|hybrid|onsite|unknown",
  "language_requirements": ["english", "french", ...],
  "must_haves": [string, ...],
  "nice_to_haves": [string, ...],
  "tags": [string, ...]
}

Rules:
- "must_haves" / "nice_to_haves" are extracted, never invented. Max 6 each.
- "tags" are short single words or two-word phrases. Max 8.
- Use lowercase for tags.

JOB:
{job}

JSON:"""


_SUMMARIZE_PROMPT = """Summarize this job posting in TWO sentences for a fast
scan. No marketing fluff. Plain English. Return JSON only.

{
  "tldr": "two-sentence summary",
  "key_signals": ["short signal 1", "short signal 2", ...]
}

JOB:
{job}

JSON:"""


def classify_job(job: JobListing, options: PolishOptions | None = None) -> Optional[dict]:
    """Return a structured classification of the job. None when AI unavailable."""
    options = options or PolishOptions.from_env()
    if not ai.is_available(options):
        return None
    prompt = _CLASSIFY_PROMPT.replace("{job}", ai._job_summary(job))
    raw = ai._call_ollama_json(prompt, options, task="classify")
    if not isinstance(raw, dict):
        return None
    role_family = str(raw.get("role_family") or "").strip().lower()
    seniority = str(raw.get("seniority") or "").strip().lower()
    contract = str(raw.get("contract") or "").strip().lower()
    remote_mode = str(raw.get("remote_mode") or "").strip().lower()
    tags = [str(t).strip().lower() for t in (raw.get("tags") or []) if str(t).strip()][:8]
    must = [str(t).strip() for t in (raw.get("must_haves") or []) if str(t).strip()][:6]
    nice = [str(t).strip() for t in (raw.get("nice_to_haves") or []) if str(t).strip()][:6]
    langs = [str(t).strip().lower() for t in (raw.get("language_requirements") or []) if str(t).strip()][:4]
    if role_family not in {"data_science", "machine_learning", "data_engineering", "data_analyst", "software", "other"}:
        role_family = "other"
    if seniority not in {"intern", "junior", "mid", "senior", "lead"}:
        seniority = ""
    if contract not in {"stage", "alternance", "cdi", "cdd", "freelance", "other"}:
        contract = ""
    if remote_mode not in {"remote", "hybrid", "onsite", "unknown"}:
        remote_mode = "unknown"
    return {
        "role_family": role_family,
        "seniority": seniority,
        "contract": contract,
        "remote_mode": remote_mode,
        "language_requirements": langs,
        "must_haves": must,
        "nice_to_haves": nice,
        "tags": tags,
    }


def summarize_job(job: JobListing, options: PolishOptions | None = None) -> Optional[dict]:
    """Return a TL;DR + key signals for the job. None when AI unavailable."""
    options = options or PolishOptions.from_env()
    if not ai.is_available(options):
        return None
    prompt = _SUMMARIZE_PROMPT.replace("{job}", ai._job_summary(job))
    raw = ai._call_ollama_json(prompt, options, task="summarize")
    if not isinstance(raw, dict):
        return None
    tldr = str(raw.get("tldr") or "").strip()
    signals = [str(s).strip() for s in (raw.get("key_signals") or []) if str(s).strip()][:6]
    if not tldr or len(tldr) > 600:
        return None
    return {"tldr": tldr, "key_signals": signals}
