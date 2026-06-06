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
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from job_agent.polish import (
    PolishOptions,
    _tokens,
    is_ollama_reachable,
    resolve_ollama_model,
)
from job_agent.agent_core import choose_route, record_trace
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


def _call_ollama_json(prompt: str, options: PolishOptions, *, task: str = "general") -> Optional[dict]:
    """Call Ollama and parse the response as JSON. Returns None on failure."""
    if requests is None:
        return None
    route = choose_route(task, prompt, options)
    payload = {
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
        return None
    raw_text = ""
    if isinstance(body, dict):
        raw_text = body.get("response", "") or body.get("thinking", "")
    if not raw_text:
        record_trace(route, ok=False, elapsed_ms=int((time.perf_counter() - started) * 1000), error="empty response")
        return None
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
    raw = _call_ollama_json(prompt, options, task="fit_analysis")
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
    raw = _call_ollama_json(prompt, options, task="tailored_summary")
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
    raw = _call_ollama_json(prompt, options, task="cover_letter_bullets")
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


def classify_job(job: JobListing, options: PolishOptions | None = None) -> Optional[dict]:
    """Return a structured classification of the job. None when AI unavailable."""
    options = options or PolishOptions.from_env()
    if not is_available(options):
        return None
    prompt = _CLASSIFY_PROMPT.replace("{job}", _job_summary(job))
    raw = _call_ollama_json(prompt, options, task="classify")
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
    if not is_available(options):
        return None
    prompt = _SUMMARIZE_PROMPT.replace("{job}", _job_summary(job))
    raw = _call_ollama_json(prompt, options, task="summarize")
    if not isinstance(raw, dict):
        return None
    tldr = str(raw.get("tldr") or "").strip()
    signals = [str(s).strip() for s in (raw.get("key_signals") or []) if str(s).strip()][:6]
    if not tldr or len(tldr) > 600:
        return None
    return {"tldr": tldr, "key_signals": signals}


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
    if not is_available(options):
        return []
    if language is None:
        language = "French" if _looks_french((job.description or "") + " " + job.title) else "English"
    prompt = (_DRAFT_LETTER_PROMPT
              .replace("{language}", language)
              .replace("{candidate}", _candidate_summary(profile, master_cv))
              .replace("{job}", _job_summary(job)))
    raw = _call_ollama_json(prompt, options, task="cover_letter_body")
    if not isinstance(raw, dict):
        return []
    paragraphs_raw = raw.get("paragraphs") or []
    if not isinstance(paragraphs_raw, list):
        return []
    allowed_tokens = _tokens(
        _candidate_summary(profile, master_cv) + " " + _job_summary(job)
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
    if not is_available(options):
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
              .replace("{candidate}", _candidate_summary(profile, master_cv))
              .replace("{job}", _job_summary(job))
              .replace("{history}", history_text)
              .replace("{question}", question[:600]))
    if requests is None:
        return None
    route = choose_route("chat", prompt, options)
    payload = {
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
    candidate_tokens = _tokens(_candidate_summary(profile, master_cv) + " " + _job_summary(job))
    reply_tokens = _tokens(reply)
    if reply_tokens:
        overlap = len(reply_tokens & candidate_tokens) / len(reply_tokens)
        if overlap < 0.25:
            record_trace(route, ok=False, elapsed_ms=int((time.perf_counter() - started) * 1000), error="grounding overlap too low")
            return None
    record_trace(route, ok=True, elapsed_ms=int((time.perf_counter() - started) * 1000))
    return reply


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
    raw = _call_ollama_json(prompt, options, task="search_plan")
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
