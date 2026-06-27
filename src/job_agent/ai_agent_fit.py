"""Fit analysis + tailored-summary / cover-bullet generation (local Ollama).

Shared helpers and the Ollama seam (``is_available`` / ``_call_ollama_json``)
are reached through the :mod:`job_agent.ai_agent` module object (``ai.<name>``)
so the ai_agent tests' ``monkeypatch.setattr(ai_agent, ...)`` seams keep working
after the split.
"""
from __future__ import annotations

from typing import Optional

import job_agent.ai_agent as ai
from job_agent.polish import PolishOptions, _tokens
from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.schemas.job import JobListing

_FIT_PROMPT = """You are a senior data science recruiter. Compare the candidate
profile below against the job posting. Return JSON only — no commentary.

JSON schema:
{
  "verdict": "strong" | "moderate" | "weak",
  "score": 0-100,
  "strengths": [string, ...],
  "gaps": [string, ...],
  "suggested_emphasis": [string, ...],
  "summary": "2-3 sentence summary",
  "confidence": 0.0-1.0
}

Rules:
- Use only facts present in the candidate or job. Do not invent metrics.
- "suggested_emphasis" lists 3-6 short bullet ideas the CV could highlight
  (e.g. "MLOps pipeline experience", "Python + Pandas data automation").
- Keep "summary" under 80 words.

CANDIDATE:
{candidate}

JOB:
{job}

JSON:"""


def analyze_fit(job: JobListing, master_cv: MasterCV, profile: CandidateProfile,
                options: PolishOptions | None = None) -> "Optional[ai.FitAnalysis]":
    """Produce a structured fit analysis. Returns None if Ollama is unavailable."""
    options = options or PolishOptions.from_env()
    if not ai.is_available(options):
        return None
    prompt = _FIT_PROMPT.replace("{candidate}", ai._candidate_summary(profile, master_cv)).replace("{job}", ai._job_summary(job))
    raw = ai._call_ollama_json(prompt, options, task="fit_analysis")
    if not isinstance(raw, dict):
        return None
    return ai.FitAnalysis.from_dict(raw)


_SUMMARY_PROMPT = """Write a 2-sentence professional CV summary for the
candidate, tailored for this specific role. Use only facts from the candidate
profile. Do not invent metrics, dates, or skills the candidate does not have.

Return JSON only:
{
  "summary": "2 sentences in plain English"
}

CANDIDATE:
{candidate}

JOB:
{job}

JSON:"""


def generate_tailored_summary(job: JobListing, master_cv: MasterCV, profile: CandidateProfile,
                              options: PolishOptions | None = None) -> Optional[str]:
    """Return a tailored summary string or None if validation fails."""
    options = options or PolishOptions.from_env()
    if not ai.is_available(options):
        return None
    base_summary = (profile.summary or master_cv.summary or "").strip()
    prompt = _SUMMARY_PROMPT.replace("{candidate}", ai._candidate_summary(profile, master_cv)).replace("{job}", ai._job_summary(job))
    raw = ai._call_ollama_json(prompt, options, task="tailored_summary")
    if not isinstance(raw, dict):
        return None
    candidate_summary = str(raw.get("summary") or "").strip()
    if not candidate_summary or len(candidate_summary) > 1200:
        return None
    # Validate: must share enough vocabulary with the base summary OR the job.
    base_tokens = _tokens(base_summary)
    candidate_tokens = _tokens(candidate_summary)
    if not candidate_tokens:
        return None
    job_tokens = _tokens(job.title + " " + " ".join(job.tech_stack + job.requirements))
    overlap_with_base = len(base_tokens & candidate_tokens) / max(1, len(base_tokens))
    overlap_with_job = len(job_tokens & candidate_tokens) / max(1, len(job_tokens))
    if overlap_with_base < 0.35 and overlap_with_job < 0.2:
        return None
    return candidate_summary


_COVER_BULLETS_PROMPT = """Suggest 2-3 short bullet sentences a candidate can
include in a cover letter to address this job. Use ONLY facts already in the
candidate profile (skills, projects, experience). Do NOT invent metrics,
sponsorship claims, salary expectations, or facts the candidate did not state.

Return JSON only:
{
  "bullets": ["sentence 1", "sentence 2", "sentence 3"]
}

CANDIDATE:
{candidate}

JOB:
{job}

JSON:"""


def generate_cover_letter_bullets(job: JobListing, master_cv: MasterCV, profile: CandidateProfile,
                                  options: PolishOptions | None = None) -> list[str]:
    """Suggest extra cover-letter bullets. Returns [] when unavailable/unsafe."""
    options = options or PolishOptions.from_env()
    if not ai.is_available(options):
        return []
    prompt = _COVER_BULLETS_PROMPT.replace("{candidate}", ai._candidate_summary(profile, master_cv)).replace("{job}", ai._job_summary(job))
    raw = ai._call_ollama_json(prompt, options, task="cover_letter_bullets")
    if not isinstance(raw, dict):
        return []
    bullets_raw = raw.get("bullets") or []
    if not isinstance(bullets_raw, list):
        return []
    # Allowed tokens come from candidate facts + the job posting. Anything
    # outside (e.g. a hallucinated company name) gets the bullet rejected.
    allowed_tokens = _tokens(
        ai._candidate_summary(profile, master_cv) + " " + ai._job_summary(job)
    )
    result: list[str] = []
    for item in bullets_raw[:5]:
        text = str(item).strip()
        if not text or len(text) > 240:
            continue
        text_tokens = _tokens(text)
        if not text_tokens:
            continue
        # 75% of bullet vocabulary must come from candidate/job. Common
        # connective words are excluded by the tokenizer.
        overlap = len(text_tokens & allowed_tokens) / len(text_tokens)
        if overlap < 0.7:
            continue
        result.append(text)
    return result[:3]
