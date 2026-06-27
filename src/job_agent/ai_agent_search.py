"""AI-assisted search-query planning with a deterministic fallback.

The Ollama seam (``is_available`` / ``_call_ollama_json``) and shared
``_candidate_summary`` come from :mod:`job_agent.ai_agent` (``ai.<name>``) so
the tests' monkeypatch seams keep working.
"""
from __future__ import annotations

import re

import job_agent.ai_agent as ai
from job_agent.polish import PolishOptions
from job_agent.schemas.candidate import CandidateProfile, MasterCV

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
    if not ai.is_available(options):
        return {
            "queries": fallback,
            "rationale": "Deterministic France/English internship expansion.",
            "used_ai": False,
            "model": "",
        }

    prompt = (
        _SEARCH_PLAN_PROMPT
        .replace("{candidate}", ai._candidate_summary(profile, master_cv))
        .replace("{seed_query}", seed_query)
        .replace("{location}", location)
        .replace("{language}", language)
        .replace("{internships_only}", str(internships_only))
        .replace("{limit}", str(limit))
    )
    raw = ai._call_ollama_json(prompt, options, task="search_plan")
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
            "model": ai.resolve_ollama_model(options),
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
        "model": ai.resolve_ollama_model(options),
    }
