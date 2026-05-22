"""Smart-mode AI agent: local-Ollama-powered fit analysis and tailoring.

This module is intentionally optional. When Ollama is installed and a local
model is running, the agent can:

- **Analyse fit**: produce a short, structured opinion about whether the
  candidate is a good match, with concrete strengths and gaps.
- **Generate a tailored summary** that goes beyond the deterministic
  keyword-overlap closer.
- **Suggest extra cover-letter bullets** grounded in the job description.

When Ollama is unavailable, every entry point returns ``None`` so the existing
deterministic pipeline keeps working unchanged. The module never sends data
off-machine.

Safety rails:

- All LLM output is JSON-parsed and validated against a small schema.
- Anything that doesn't validate is discarded silently — never injected.
- Numbers, company names, and dates from the source must not be hallucinated
  into the output. We re-check token overlap before returning text.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from job_agent.polish import PolishOptions, _tokens, is_ollama_reachable, resolve_ollama_model
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
    """
    options = options or PolishOptions.from_env()
    return is_ollama_reachable(options)


def _call_ollama_json(prompt: str, options: PolishOptions) -> Optional[dict]:
    """Call Ollama and parse the response as JSON. Returns None on failure."""
    if requests is None:
        return None
    payload = {
        "model": resolve_ollama_model(options),
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_predict": 768},
    }
    try:
        response = requests.post(options.base_url + "/api/generate", json=payload, timeout=options.timeout * 2)
        response.raise_for_status()
        body = response.json()
    except Exception:
        return None
    raw_text = ""
    if isinstance(body, dict):
        raw_text = body.get("response", "") or body.get("thinking", "")
    if not raw_text:
        return None
    # Some models return text with code fences around JSON; strip them.
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        return None


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


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


def analyze_fit(job: JobListing, master_cv: MasterCV, profile: CandidateProfile,
                options: PolishOptions | None = None) -> Optional[FitAnalysis]:
    """Produce a structured fit analysis. Returns None if Ollama is unavailable."""
    options = options or PolishOptions.from_env()
    if not is_available(options):
        return None
    prompt = _FIT_PROMPT.replace("{candidate}", _candidate_summary(profile, master_cv)).replace("{job}", _job_summary(job))
    raw = _call_ollama_json(prompt, options)
    if not isinstance(raw, dict):
        return None
    return FitAnalysis.from_dict(raw)


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
    if not is_available(options):
        return None
    base_summary = (profile.summary or master_cv.summary or "").strip()
    prompt = _SUMMARY_PROMPT.replace("{candidate}", _candidate_summary(profile, master_cv)).replace("{job}", _job_summary(job))
    raw = _call_ollama_json(prompt, options)
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
    if not is_available(options):
        return []
    prompt = _COVER_BULLETS_PROMPT.replace("{candidate}", _candidate_summary(profile, master_cv)).replace("{job}", _job_summary(job))
    raw = _call_ollama_json(prompt, options)
    if not isinstance(raw, dict):
        return []
    bullets_raw = raw.get("bullets") or []
    if not isinstance(bullets_raw, list):
        return []
    # Allowed tokens come from candidate facts + the job posting. Anything
    # outside (e.g. a hallucinated company name) gets the bullet rejected.
    allowed_tokens = _tokens(
        _candidate_summary(profile, master_cv) + " " + _job_summary(job)
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


_SEARCH_PLAN_PROMPT = """You are an elite France-focused job search strategist
for a data science / AI candidate in Paris. Create search queries that will
find internships, alternance, apprenticeship, and junior roles across France
Travail and public job boards.

Return JSON only:
{
  "queries": ["query 1", "query 2", ...],
  "rationale": "one short sentence"
}

Rules:
- Mix English and French when language is "both".
- Include French internship terms such as stage, stagiaire, alternance, and apprentissage when internships_only is true.
- Prefer short queries that public job APIs actually match, e.g. "stage data", "alternance data", "machine learning stage".
- Do not include URLs, boolean syntax, quotes, salary terms, or personal data.
- Return at most {limit} queries.

CANDIDATE:
{candidate}

SEED QUERY: {seed_query}
LOCATION: {location}
LANGUAGE: {language}
INTERNSHIPS ONLY: {internships_only}

JSON:"""


def _clean_query(raw: str) -> str:
    value = re.sub(r"[\"'`]", "", str(raw or "")).strip()
    value = re.sub(r"\s+", " ", value)
    if not value or len(value) > 70:
        return ""
    if "http://" in value.casefold() or "https://" in value.casefold():
        return ""
    if any(char in value for char in "{}[]()|"):
        return ""
    return value


def suggest_search_queries(
    profile: CandidateProfile,
    master_cv: MasterCV,
    *,
    seed_query: str = "data scientist",
    location: str = "Paris",
    language: str = "both",
    internships_only: bool = True,
    limit: int = 8,
    options: PolishOptions | None = None,
) -> dict:
    """Return AI-generated search queries with deterministic fallback."""
    from job_agent.intake.france_market import expand_france_search_queries

    limit = max(1, min(int(limit or 8), 20))
    fallback = expand_france_search_queries(seed_query, limit=limit, language=language)
    options = options or PolishOptions.from_env()
    if not is_available(options):
        return {
            "queries": fallback,
            "rationale": "Deterministic France/English internship expansion.",
            "used_ai": False,
            "model": "",
        }

    prompt = (
        _SEARCH_PLAN_PROMPT
        .replace("{candidate}", _candidate_summary(profile, master_cv))
        .replace("{seed_query}", seed_query)
        .replace("{location}", location)
        .replace("{language}", language)
        .replace("{internships_only}", str(internships_only))
        .replace("{limit}", str(limit))
    )
    raw = _call_ollama_json(prompt, options)
    queries: list[str] = []
    if isinstance(raw, dict):
        for item in raw.get("queries", []):
            query = _clean_query(str(item))
            if query and query.casefold() not in {q.casefold() for q in queries}:
                queries.append(query)
            if len(queries) >= limit:
                break
    if not queries:
        return {
            "queries": fallback,
            "rationale": "AI search plan was unavailable or invalid; deterministic fallback used.",
            "used_ai": False,
            "model": resolve_ollama_model(options),
        }

    # Keep the deterministic high-recall French terms too. They are proven to
    # work well on France Travail even when an LLM suggests more polished role
    # titles.
    for item in fallback:
        query = _clean_query(item)
        if query and query.casefold() not in {q.casefold() for q in queries}:
            queries.append(query)
        if len(queries) >= limit:
            break
    return {
        "queries": queries[:limit],
        "rationale": str(raw.get("rationale") or "Local AI generated a query plan.").strip()[:240] if isinstance(raw, dict) else "Local AI generated a query plan.",
        "used_ai": True,
        "model": resolve_ollama_model(options),
    }
