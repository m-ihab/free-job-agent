"""Shared core for free/public job-source API connectors.

Holds the common types (:class:`FreeApiError`, :class:`FreeApiSearch`,
:class:`SourceInfo`), HTTP helpers, and the post-filter/ranking pipeline shared
by every provider module under :mod:`job_agent.intake.sources`.

The :class:`SourceClient` Protocol describes the call shape every provider
module exposes: a single ``fetch(search) -> list[JobListing]`` callable.

HTTP is performed via the module-level ``requests`` symbol (attribute access on
the live ``requests`` module). Tests monkeypatch ``requests.get`` / ``requests.post``
on the shared module object, so every provider transitively sees the patch.
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

import requests

from job_agent.intake.api_cache import read_cached_json, write_cached_json
from job_agent.intake.url import HEADERS
from job_agent.intake.internships import is_internship_listing, is_stage_listing, is_alternance_listing
from job_agent.normalizer import normalize
from job_agent.search_quality import assess_search_quality
from job_agent.schemas.job import JobListing
from job_agent.utils.html import strip_html

DEFAULT_TIMEOUT = 20
MAX_LIMIT = 100
DEFAULT_CACHE_TTL_HOURS = 6.0


class FreeApiError(RuntimeError):
    """Raised when a public job-source API cannot be queried safely."""


# France Travail typeContrat codes for contract filtering.
_CONTRACT_TYPE_FT: dict[str, str] = {
    "stage": "STG",
    "alternance": "CA1,CA2",
    "stage_and_alternance": "STG,CA1,CA2",
}

# Words that should appear in at least one title token for a job to be tech-relevant.
_DATA_TECH_TITLE_TOKENS: frozenset[str] = frozenset({
    "data", "science", "scientist", "analyst", "analytics", "engineer", "engineering",
    "machine", "learning", "intelligence", "artificielle", "artificial", "nlp", "llm",
    "computer", "vision", "python", "sql", "backend", "frontend", "developer", "software",
    "ia", "ml", "ai", "bi", "etl", "mlops", "devops", "cloud", "platform", "research",
    "modélisation", "modelisation", "statistique", "statisticien", "informaticien",
    "chargé", "charge", "études", "etudes", "développeur", "developpeur",
    "digital", "numerique", "numérique", "deep", "mining", "warehouse", "inference",
    "ingénieur", "ingenieur", "fullstack", "tech", "big", "automatique", "apprentissage",
    "architecture", "securite", "sécurité", "réseau", "reseau", "cybersecurity",
})

# Non-tech retail/manual roles that should never enter the tracker.
_BLOCKED_ROLE_PREFIXES: tuple[str, ...] = (
    "vendeur", "vendeuse", "caissier", "caissière", "caissiere",
    "aide-soignant", "aide soignant", "infirmier", "infirmière",
    "secrétaire", "secretaire", "comptable", "chauffeur",
    "livreur", "livreuse", "opérateur de saisie", "manutentionnaire",
    "électricien", "electricien", "plombier", "menuisier",
    "cuisinier", "cuisinière", "cuisiniere", "serveur", "serveuse",
    "conseiller de vente", "conseillère de vente",
    "technicien de maintenance", "technicien de production",
    "agent de sécurité", "agent de securite", "gardien",
    "commercial terrain", "commercial itinérant",
)


def _is_tech_relevant_title(job: "JobListing") -> bool:
    """Return True when the job title plausibly belongs in a tech/data list.

    Hard-blocks obvious non-tech retail/manual roles first, then requires at
    least one tech token OR two tech-stack entries. This prevents queries like
    'alternance data' from returning 'Vendeur en magasin' whose description
    mentions a POS 'data terminal'.
    """
    title_lower = job.title.casefold()
    for blocked in _BLOCKED_ROLE_PREFIXES:
        if blocked in title_lower:
            return False
    tokens = set(re.split(r"[\s\-/|,]+", title_lower))
    if tokens & _DATA_TECH_TITLE_TOKENS:
        return True
    if len(job.tech_stack) >= 2:
        return True
    return False


@dataclass(frozen=True)
class FreeApiSearch:
    """Parameters for a read-only public job search."""

    source: str
    query: str = ""
    location: str = ""
    country: str = ""
    board: str = ""
    limit: int = 20
    page: int = 1
    remote_only: bool = False
    internships_only: bool = False
    contract_type: str = ""   # "stage" | "alternance" | "stage_and_alternance" | "" (all)
    min_relevance: int = 0
    france_eu_only: bool = False
    radius_km: int = 0
    timeout: int = DEFAULT_TIMEOUT
    use_cache: bool = False
    cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS


@dataclass(frozen=True)
class SourceInfo:
    name: str
    description: str
    requires_board: bool = False
    board_label: str = "board"
    requires_env: tuple[str, ...] = ()


class SourceClient(Protocol):
    """Call shape for a provider module's fetcher.

    Each provider module under :mod:`job_agent.intake.sources` exposes a
    ``fetch`` callable matching this Protocol.
    """

    def __call__(self, search: FreeApiSearch) -> list[JobListing]: ...


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit or 20), MAX_LIMIT))


def _get_json(  # noqa: PLR0913 — low-level HTTP helper; kwargs map 1:1 to request options
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    extra_headers: dict[str, str] | None = None,
    use_cache: bool = False,
    cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
) -> Any:
    clean_params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    if use_cache:
        cached = read_cached_json(url, clean_params, cache_ttl_hours)
        if cached is not None:
            return cached
    headers = {**HEADERS, **(extra_headers or {})}
    response = requests.get(url, params=clean_params, headers=headers, timeout=timeout)
    response.raise_for_status()
    status_code = getattr(response, "status_code", None)
    content = getattr(response, "content", b"content")
    if status_code == 204 or content == b"":
        return {}
    try:
        payload = response.json()
    except ValueError as exc:
        content_type = response.headers.get("Content-Type", "unknown")
        raise FreeApiError(
            f"API returned a non-JSON response (HTTP {response.status_code}, Content-Type: {content_type}). "
            "Check the API base URL, endpoint path, credentials, and scopes."
        ) from exc
    if use_cache:
        write_cached_json(url, clean_params, payload)
    return payload


def _fetch_json(
    search: FreeApiSearch,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    return _get_json(
        url,
        params=params,
        timeout=search.timeout,
        extra_headers=extra_headers,
        use_cache=search.use_cache,
        cache_ttl_hours=search.cache_ttl_hours,
    )


def _as_dict(value: Any) -> dict[str, Any]:
    """Return ``value`` when it is a dict, else an empty dict.

    Behaviour-identical to the inline ``value if isinstance(value, dict) else {}``
    idiom, but typed so callers narrow to ``dict[str, Any]`` cleanly.
    """
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """Return ``value`` when it is a list, else an empty list."""
    return value if isinstance(value, list) else []


def _strip_html(value: Any) -> str:
    text = "" if value is None else str(value)
    if not text:
        return ""
    cleaned = strip_html(text, blocked_tags={"script", "style", "noscript"}, separator="\n")
    cleaned = html_lib.unescape(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        result = []
        for item in value:
            if isinstance(item, dict):
                label = item.get("name") or item.get("title") or item.get("label") or item.get("location")
            else:
                label = item
            label = str(label).strip() if label is not None else ""
            if label:
                result.append(label)
        return result
    return [str(value).strip()] if str(value).strip() else []


def _join_nonempty(*parts: Any, sep: str = "\n\n") -> str:
    cleaned = [str(p).strip() for p in parts if p is not None and str(p).strip()]
    return sep.join(cleaned)


def _first_nonempty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, list) and value:
            value = value[0]
        text = str(value).strip()
        if text:
            return text
    return ""


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


_STOPWORDS = {"a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "is", "are", "with", "by", "from", "as", "be", "le", "la", "les", "de", "du", "des", "et", "ou", "pour", "en", "sur", "dans"}

# Synonyms expand query coverage: "data scientist" should match "data science",
# "machine learning engineer" → "ml engineer", etc.
_QUERY_SYNONYMS = {
    "scientist": ("scientist", "science", "scientifique"),
    "science": ("science", "scientist", "scientifique"),
    "engineer": ("engineer", "engineering", "engineer.", "ingénieur", "ingenieur"),
    "engineering": ("engineering", "engineer", "ingénierie", "ingenierie"),
    "analyst": ("analyst", "analytics", "analyse", "analyste"),
    "analytics": ("analytics", "analyst", "analyse"),
    "machine": ("machine", "ml", "ai"),
    "learning": ("learning", "apprentissage"),
    "intelligence": ("intelligence", "ia", "ai"),
    "artificial": ("artificial", "ai", "ia"),
    "developer": ("developer", "développeur", "developpeur", "engineer"),
    "stage": ("stage", "stagiaire", "internship", "intern"),
    "stagiaire": ("stagiaire", "stage", "intern", "internship"),
    "internship": ("internship", "intern", "stage", "stagiaire"),
    "intern": ("intern", "internship", "stage", "stagiaire"),
    "alternance": ("alternance", "apprentissage", "apprenticeship", "apprentice"),
    "apprentissage": ("apprentissage", "alternance", "apprentice"),
}


# Compiled \b<word>\b patterns are reused across the thousands of token checks
# a multi-source search performs, instead of recompiling on every call.
_WORD_PATTERN_CACHE: dict[str, "re.Pattern[str]"] = {}


def _word_pattern(word: str) -> "re.Pattern[str]":
    pattern = _WORD_PATTERN_CACHE.get(word)
    if pattern is None:
        pattern = re.compile(r"\b" + re.escape(word) + r"\b")
        _WORD_PATTERN_CACHE[word] = pattern
    return pattern


def _token_match(token: str, haystack: str) -> bool:
    """Match a token (or any of its synonyms) as a whole word in haystack.

    Word-boundary matching avoids false positives like ``data`` matching
    inside ``database`` or ``ai`` matching inside ``main``.
    """
    synonyms = _QUERY_SYNONYMS.get(token, (token,))
    for syn in synonyms:
        if not syn:
            continue
        if _word_pattern(syn).search(haystack):
            return True
    return False


def _contains_query(job: JobListing, query: str) -> bool:
    """Strict match: the job's title must mention the role.

    APIs like Remotive ignore their own ``search`` parameter and return all
    recent jobs, so client-side filtering is mandatory. Title is the most
    reliable signal; descriptions and tags are too noisy and produce
    "Senior Cinematic Video Editor" matches for "machine learning".
    """
    if not query.strip():
        return True
    title = job.title.casefold()
    raw_tokens = [t for t in re.split(r"\s+", query.casefold().strip()) if t]
    meaningful = [t for t in raw_tokens if len(t) >= 2 and t not in _STOPWORDS]
    if not meaningful:
        return True
    return any(_token_match(token, title) for token in meaningful)


_LOCATION_ALIASES = {
    "paris": ("paris", "75 -", "île-de-france", "ile-de-france", "idf", "france"),
    "île-de-france": ("paris", "75 -", "77 -", "78 -", "91 -", "92 -", "93 -", "94 -", "95 -", "île-de-france", "ile-de-france", "idf", "france"),
    "ile-de-france": ("paris", "75 -", "77 -", "78 -", "91 -", "92 -", "93 -", "94 -", "95 -", "île-de-france", "ile-de-france", "idf", "france"),
    "idf": ("paris", "75 -", "77 -", "78 -", "91 -", "92 -", "93 -", "94 -", "95 -", "île-de-france", "ile-de-france", "idf", "france"),
    "france": ("france", "paris", "lyon", "marseille", "lille", "toulouse", "nantes"),
    "europe": ("europe", "france", "germany", "netherlands", "spain", "italy", "uk", "united kingdom", "ireland", "portugal"),
    "remote": ("remote", "worldwide", "anywhere", "global"),
    "worldwide": ("remote", "worldwide", "anywhere", "global"),
    "anywhere": ("remote", "worldwide", "anywhere", "global"),
}
_REMOTE_LOCATION_KEYS = {"remote", "worldwide", "anywhere", "global"}


def _contains_location(job: JobListing, location: str) -> bool:
    if not location.strip():
        return True
    key = location.casefold().strip()
    # Remote jobs pass automatically only when the user explicitly searches for
    # remote/worldwide roles. For Paris/France searches, a global remote job is
    # usually clutter unless the posting also mentions the target geography.
    if job.remote and key in _REMOTE_LOCATION_KEYS:
        return True
    haystack = "\n".join([job.location or "", job.description or "", job.raw_text or ""]).casefold()
    aliases = _LOCATION_ALIASES.get(key, (key,))
    return any(alias in haystack for alias in aliases)


def _query_score(job: JobListing, query: str) -> int:
    """Rank job relevance to query — used to sort results, not to drop them."""
    if not query.strip():
        return 0
    title = job.title.casefold()
    desc = (job.description or "").casefold()
    stack = " ".join(job.tech_stack).casefold()
    tokens = [t for t in re.split(r"\s+", query.casefold().strip()) if len(t) >= 2 and t not in _STOPWORDS]
    score = 0
    for token in tokens:
        synonyms = _QUERY_SYNONYMS.get(token, (token,))
        for syn in synonyms:
            if syn in title:
                score += 10
            if syn in stack:
                score += 5
            if syn in desc:
                score += 2
    return score


def _post_filter(jobs: list[JobListing], search: FreeApiSearch, apply_query_filter: bool = True) -> list[JobListing]:
    """Filter results then rank by query relevance.

    Source APIs that accept a search parameter (Remotive, RemoteOK, etc.) have
    already done the keyword filtering. We enforce contract type, location,
    relevance, and tech-title constraints here, then sort by relevance.

    ``apply_query_filter`` keeps only jobs whose title/description actually match
    the query (``_contains_query``, which expands FR/EN synonyms). Leaving it on
    is what keeps off-topic rows like "Informaticien" or "Master SI/Finance
    Business" out of a "data scientist" search. The query-relevance *score*
    (``assess_search_quality``) is recorded for ranking/UI but is intentionally
    not used as a hard cutoff here, since it is tuned for data roles and would
    over-filter legitimate adjacent roles (e.g. a plain "Python Engineer").
    """
    # Resolve effective contract filter (contract_type takes precedence, then internships_only legacy flag).
    ct = (search.contract_type or "").strip().lower()
    if not ct and search.internships_only:
        ct = "stage_and_alternance"

    filtered: list[JobListing] = []
    for job in jobs:
        # Title-quality gate: block non-tech roles (e.g. "Vendeur en magasin").
        if not _is_tech_relevant_title(job):
            continue
        # Contract-type filter.
        if ct == "stage":
            if not is_stage_listing(job):
                continue
        elif ct == "alternance":
            if not is_alternance_listing(job):
                continue
        elif ct in ("stage_and_alternance", "both"):
            if not is_internship_listing(job):
                continue
        if search.remote_only and not job.remote:
            continue
        if apply_query_filter and not _contains_query(job, search.query):
            continue
        if not _contains_location(job, search.location):
            continue
        quality = assess_search_quality(job, query=search.query, location=search.location)
        # JobListing uses pydantic v1 `extra="allow"`, so these dynamic search-result
        # attributes are valid at runtime but not declared as model fields.
        job.search_quality_score = quality["score"]  # type: ignore[attr-defined]
        job.search_role_family = quality["role_family"]  # type: ignore[attr-defined]
        job.search_contract = quality["contract"]  # type: ignore[attr-defined]
        job.search_quality_flags = quality["flags"]  # type: ignore[attr-defined]
        if search.france_eu_only and "outside-target-region" in quality["flags"]:
            continue
        if search.min_relevance and int(quality["score"]) < int(search.min_relevance):
            continue
        filtered.append(job)
    if search.query.strip():
        filtered.sort(key=lambda j: (-_query_score(j, search.query), j.created_at), reverse=False)
    return filtered[: _bounded_limit(search.limit)]


def _make_job(**kwargs: Any) -> JobListing:
    job = JobListing(**kwargs)
    return normalize(job)
