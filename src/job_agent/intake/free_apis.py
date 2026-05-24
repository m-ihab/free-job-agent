"""Free/public job-source API ingestion.

These connectors are intentionally read-only. They fetch public job postings from
sources that expose unauthenticated JSON feeds, free-key APIs, or public ATS
job-board feeds and normalize them into :class:`JobListing` objects. They do not
create accounts, log in, bypass access controls, or submit applications.
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from job_agent.intake.api_cache import read_cached_json, write_cached_json
from job_agent.intake.france_travail_auth import (
    france_travail_env,
    france_travail_token,
    invalidate_france_travail_token_cache,
)
from job_agent.intake.url import HEADERS
from job_agent.intake.internships import is_internship_listing
from job_agent.normalizer import normalize
from job_agent.search_quality import assess_search_quality
from job_agent.secrets import load_local_env
from job_agent.schemas.job import JobListing
from job_agent.utils.html import strip_html

DEFAULT_TIMEOUT = 20
MAX_LIMIT = 100
DEFAULT_CACHE_TTL_HOURS = 6.0


class FreeApiError(RuntimeError):
    """Raised when a public job-source API cannot be queried safely."""


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


SUPPORTED_SOURCES: dict[str, SourceInfo] = {
    "remotive": SourceInfo("remotive", "Remotive remote jobs public API"),
    "remoteok": SourceInfo("remoteok", "Remote OK public JSON feed"),
    "himalayas": SourceInfo("himalayas", "Himalayas remote jobs public JSON API"),
    "arbeitnow": SourceInfo("arbeitnow", "Arbeitnow free Europe/remote job board API"),
    "jobicy": SourceInfo("jobicy", "Jobicy remote jobs JSON feed"),
    "themuse": SourceInfo("themuse", "The Muse public jobs API"),
    "greenhouse": SourceInfo("greenhouse", "Greenhouse public Job Board API", True, "Greenhouse board token"),
    "lever": SourceInfo("lever", "Lever public Postings API", True, "Lever site slug"),
    "ashby": SourceInfo("ashby", "Ashby public Job Postings API", True, "Ashby job board name"),
    "recruitee": SourceInfo("recruitee", "Recruitee public company offers API", True, "Recruitee company slug"),
    "smartrecruiters": SourceInfo("smartrecruiters", "SmartRecruiters public postings API", True, "SmartRecruiters company slug"),
    "workable": SourceInfo("workable", "Workable public account jobs API", True, "Workable account slug"),
    "personio": SourceInfo("personio", "Personio public XML jobs feed", True, "Personio company slug (subdomain)"),
    "francetravail": SourceInfo(
        "francetravail",
        "France Travail Offres d'emploi API; free habilitation credentials required",
        requires_env=("FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET"),
    ),
    "labonnealternance": SourceInfo(
        "labonnealternance",
        "La bonne alternance apprenticeship opportunities API; free bearer token required",
        requires_env=("APPRENTISSAGE_API_TOKEN",),
    ),
}

_SOURCE_ALIASES = {
    "remote-ok": "remoteok",
    "remote_ok": "remoteok",
    "remote ok": "remoteok",
    "himalaya": "himalayas",
    "arbeit-now": "arbeitnow",
    "worknow": "arbeitnow",
    "gh": "greenhouse",
    "france-travail": "francetravail",
    "poleemploi": "francetravail",
    "pôle emploi": "francetravail",
    "pole-emploi": "francetravail",
    "apprentissage": "labonnealternance",
    "la-bonne-alternance": "labonnealternance",
    "lba": "labonnealternance",
    "the-muse": "themuse",
    "the_muse": "themuse",
    "muse": "themuse",
    "smart-recruiters": "smartrecruiters",
    "smart_recruiters": "smartrecruiters",
    "sr": "smartrecruiters",
}


def supported_source_names() -> list[str]:
    return sorted(SUPPORTED_SOURCES)


def canonical_source(source: str) -> str:
    key = (source or "").strip().lower()
    key = _SOURCE_ALIASES.get(key, key)
    if key not in SUPPORTED_SOURCES:
        valid = ", ".join(supported_source_names())
        raise FreeApiError(f"Unsupported source '{source}'. Supported sources: {valid}")
    return key


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit or 20), MAX_LIMIT))


def _get_json(
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


def _token_match(token: str, haystack: str) -> bool:
    """Match a token (or any of its synonyms) as a whole word in haystack.

    Word-boundary matching avoids false positives like ``data`` matching
    inside ``database`` or ``ai`` matching inside ``main``.
    """
    synonyms = _QUERY_SYNONYMS.get(token, (token,))
    for syn in synonyms:
        if not syn:
            continue
        pattern = r"\b" + re.escape(syn) + r"\b"
        if re.search(pattern, haystack):
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
    already done the keyword filtering. We only enforce remote/internship/
    location constraints here, then sort by relevance to surface the best
    matches first.
    """
    filtered: list[JobListing] = []
    for job in jobs:
        if search.internships_only and not is_internship_listing(job):
            continue
        if search.remote_only and not job.remote:
            continue
        if apply_query_filter and not _contains_query(job, search.query):
            continue
        if not _contains_location(job, search.location):
            continue
        quality = assess_search_quality(job, query=search.query, location=search.location)
        job.search_quality_score = quality["score"]
        job.search_role_family = quality["role_family"]
        job.search_contract = quality["contract"]
        job.search_quality_flags = quality["flags"]
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


def _fetch_remotive(search: FreeApiSearch) -> list[JobListing]:
    data = _fetch_json(
        search,
        "https://remotive.com/api/remote-jobs",
        params={"search": search.query, "limit": _bounded_limit(search.limit)},
    )
    items = data.get("jobs", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _strip_html(item.get("description"))
        tags = _string_list(item.get("tags"))
        location = item.get("candidate_required_location") or item.get("location") or "Remote"
        jobs.append(_make_job(
            source="api:remotive",
            source_url=item.get("url"),
            apply_url=item.get("url"),
            raw_text=_join_nonempty(item.get("title"), item.get("company_name"), location, desc),
            title=item.get("title") or "[To Be Parsed]",
            company=item.get("company_name") or "[To Be Parsed]",
            location=location,
            remote=True,
            work_mode="remote",
            job_type=item.get("job_type"),
            description=desc,
            requirements=[],
            tech_stack=tags,
            posted_date=item.get("publication_date"),
        ))
    return _post_filter(jobs, search)


def _fetch_remoteok(search: FreeApiSearch) -> list[JobListing]:
    data = _fetch_json(search, "https://remoteok.com/api")
    items = data if isinstance(data, list) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict) or "position" not in item:
            continue
        desc = _strip_html(item.get("description"))
        tags = _string_list(item.get("tags"))
        jobs.append(_make_job(
            source="api:remoteok",
            source_url=item.get("url") or item.get("apply_url"),
            apply_url=item.get("apply_url") or item.get("url"),
            raw_text=_join_nonempty(item.get("position"), item.get("company"), item.get("location"), desc, " ".join(tags)),
            title=item.get("position") or "[To Be Parsed]",
            company=item.get("company") or "[To Be Parsed]",
            location=item.get("location") or "Remote",
            remote=True,
            work_mode="remote",
            salary_min=item.get("salary_min") or None,
            salary_max=item.get("salary_max") or None,
            description=desc,
            tech_stack=tags,
            posted_date=item.get("date"),
        ))
    return _post_filter(jobs, search)


def _himalayas_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("jobs", "data", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def _fetch_himalayas(search: FreeApiSearch) -> list[JobListing]:
    params: dict[str, Any] = {"q": search.query, "sort": "recent", "page": max(1, search.page)}
    if search.country:
        params["country"] = search.country
    if search.remote_only:
        params["worldwide"] = "true"
    data = _fetch_json(search, "https://himalayas.app/jobs/api/search", params=params)
    jobs: list[JobListing] = []
    for item in _himalayas_items(data):
        desc = _strip_html(item.get("description") or item.get("descriptionHtml") or item.get("excerpt"))
        locations = _string_list(item.get("locationRestrictions") or item.get("locations") or item.get("location"))
        categories = _string_list(item.get("category") or item.get("categories") or item.get("parentCategories"))
        company = item.get("companyName") or item.get("company") or "[To Be Parsed]"
        url = item.get("applicationLink") or item.get("applyUrl") or item.get("jobUrl") or item.get("url")
        jobs.append(_make_job(
            source="api:himalayas",
            source_url=item.get("jobUrl") or url,
            apply_url=url,
            raw_text=_join_nonempty(item.get("title"), company, ", ".join(locations), item.get("excerpt"), desc),
            title=item.get("title") or "[To Be Parsed]",
            company=company,
            location=", ".join(locations) or "Remote",
            remote=True,
            work_mode="remote",
            job_type=item.get("employmentType"),
            salary_min=item.get("minSalary"),
            salary_max=item.get("maxSalary"),
            salary_currency=item.get("currency") or "USD",
            description=desc,
            tech_stack=categories,
            posted_date=item.get("postedAt") or item.get("publishedAt"),
        ))
    return _post_filter(jobs, search)


def _fetch_arbeitnow(search: FreeApiSearch) -> list[JobListing]:
    params: dict[str, Any] = {"page": max(1, search.page)}
    if search.remote_only:
        params["remote"] = "true"
    data = _fetch_json(search, "https://www.arbeitnow.com/api/job-board-api", params=params)
    items = data.get("data", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _strip_html(item.get("description"))
        tags = _string_list(item.get("tags") or item.get("job_types"))
        location = item.get("location") or ""
        jobs.append(_make_job(
            source="api:arbeitnow",
            source_url=item.get("url"),
            apply_url=item.get("url"),
            raw_text=_join_nonempty(item.get("title"), item.get("company_name"), location, desc, " ".join(tags)),
            title=item.get("title") or "[To Be Parsed]",
            company=item.get("company_name") or "[To Be Parsed]",
            location=location or None,
            remote=bool(item.get("remote")),
            work_mode="remote" if item.get("remote") else None,
            job_type=", ".join(_string_list(item.get("job_types"))) or None,
            description=desc,
            tech_stack=tags,
            posted_date=str(item.get("created_at")) if item.get("created_at") else None,
        ))
    return _post_filter(jobs, search)


def _fetch_greenhouse(search: FreeApiSearch) -> list[JobListing]:
    if not search.board:
        raise FreeApiError("greenhouse requires --board with the Greenhouse board token, for example: greenhouse --board example")
    data = _fetch_json(
        search,
        f"https://boards-api.greenhouse.io/v1/boards/{search.board}/jobs",
        params={"content": "true"},
    )
    items = data.get("jobs", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _strip_html(item.get("content"))
        departments = _string_list(item.get("departments"))
        offices = _string_list(item.get("offices"))
        location = (item.get("location") or {}).get("name") if isinstance(item.get("location"), dict) else item.get("location")
        jobs.append(_make_job(
            source="api:greenhouse",
            source_url=item.get("absolute_url"),
            apply_url=item.get("absolute_url"),
            raw_text=_join_nonempty(item.get("title"), search.board, location, desc, " ".join(departments), " ".join(offices)),
            title=item.get("title") or "[To Be Parsed]",
            company=search.board,
            location=location,
            remote="remote" in (str(location).lower() + " " + desc.lower()),
            description=desc,
            tech_stack=departments,
            posted_date=item.get("updated_at"),
        ))
    return _post_filter(jobs, search)


def _lever_location(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return ""


def _fetch_lever(search: FreeApiSearch) -> list[JobListing]:
    if not search.board:
        raise FreeApiError("lever requires --board with the Lever site slug, for example: lever --board leverdemo")
    data = _fetch_json(
        search,
        f"https://api.lever.co/v0/postings/{search.board}",
        params={"mode": "json", "limit": _bounded_limit(search.limit)},
    )
    items = data if isinstance(data, list) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        lists = item.get("lists") or []
        list_text = []
        if isinstance(lists, list):
            for block in lists:
                if isinstance(block, dict):
                    list_text.append(_join_nonempty(block.get("text"), block.get("content")))
        desc = _strip_html(_join_nonempty(item.get("description"), item.get("descriptionPlain"), item.get("additionalPlain"), "\n".join(list_text)))
        categories = item.get("categories") or {}
        team = categories.get("team") if isinstance(categories, dict) else None
        commitment = categories.get("commitment") if isinstance(categories, dict) else None
        location = _lever_location(categories.get("location") if isinstance(categories, dict) else None)
        jobs.append(_make_job(
            source="api:lever",
            source_url=item.get("hostedUrl") or item.get("applyUrl"),
            apply_url=item.get("hostedUrl") or item.get("applyUrl"),
            raw_text=_join_nonempty(item.get("text"), search.board, location, commitment, desc),
            title=item.get("text") or "[To Be Parsed]",
            company=search.board,
            location=location or None,
            remote="remote" in (location.lower() + " " + desc.lower()),
            work_mode="remote" if "remote" in (location.lower() + " " + desc.lower()) else None,
            job_type=commitment,
            description=desc,
            tech_stack=_string_list(team),
            posted_date=str(item.get("createdAt")) if item.get("createdAt") else None,
        ))
    return _post_filter(jobs, search)


def _fetch_ashby(search: FreeApiSearch) -> list[JobListing]:
    if not search.board:
        raise FreeApiError("ashby requires --board with the Ashby job board name, for example: ashby --board Ashby")
    data = _fetch_json(
        search,
        f"https://api.ashbyhq.com/posting-api/job-board/{search.board}",
        params={"includeCompensation": "true"},
    )
    items = data.get("jobs", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _strip_html(item.get("descriptionPlain") or item.get("descriptionHtml"))
        location = item.get("location") or ""
        comp = item.get("compensation") or {}
        salary_min = salary_max = None
        salary_currency = "USD"
        if isinstance(comp, dict):
            for component in comp.get("summaryComponents", []) or []:
                if not isinstance(component, dict):
                    continue
                if component.get("compensationType") == "Salary":
                    salary_min = component.get("minValue")
                    salary_max = component.get("maxValue")
                    salary_currency = component.get("currencyCode") or salary_currency
                    break
        jobs.append(_make_job(
            source="api:ashby",
            source_url=item.get("jobUrl"),
            apply_url=item.get("applyUrl") or item.get("jobUrl"),
            raw_text=_join_nonempty(item.get("title"), search.board, location, item.get("department"), item.get("team"), desc),
            title=item.get("title") or "[To Be Parsed]",
            company=search.board,
            location=location or None,
            remote=bool(item.get("isRemote")) or str(item.get("workplaceType", "")).lower() == "remote",
            work_mode=str(item.get("workplaceType") or "").lower() or None,
            job_type=item.get("employmentType"),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            description=desc,
            tech_stack=_string_list([item.get("department"), item.get("team")]),
            posted_date=item.get("publishedAt"),
        ))
    return _post_filter(jobs, search)


def _fetch_jobicy(search: FreeApiSearch) -> list[JobListing]:
    params: dict[str, Any] = {"count": _bounded_limit(search.limit)}
    location_key = (search.location or search.country or "").strip().casefold()
    geo_map = {
        "france": "france",
        "paris": "france",
        "europe": "europe",
        "united kingdom": "uk",
        "uk": "uk",
        "usa": "usa",
        "united states": "usa",
        "germany": "germany",
        "spain": "spain",
        "italy": "italy",
        "netherlands": "netherlands",
        "anywhere": "anywhere",
        "worldwide": "anywhere",
        "remote": "anywhere",
    }
    geo = geo_map.get(location_key)
    if geo:
        params["geo"] = geo
    if search.query:
        params["tag"] = search.query
    data = _fetch_json(search, "https://jobicy.com/api/v2/remote-jobs", params=params)
    items = data.get("jobs", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _strip_html(item.get("jobDescription") or item.get("jobExcerpt") or "")
        tags = _string_list(item.get("jobIndustry")) + _string_list(item.get("jobType"))
        location = item.get("jobGeo") or "Remote"
        url = item.get("url") or item.get("jobUrl")
        jobs.append(_make_job(
            source="api:jobicy",
            source_url=url,
            apply_url=url,
            raw_text=_join_nonempty(item.get("jobTitle"), item.get("companyName"), location, desc, " ".join(tags)),
            title=item.get("jobTitle") or "[To Be Parsed]",
            company=item.get("companyName") or "[To Be Parsed]",
            location=location,
            remote=True,
            work_mode="remote",
            job_type=", ".join(_string_list(item.get("jobType"))) or None,
            description=desc,
            tech_stack=tags,
            posted_date=item.get("pubDate"),
        ))
    return _post_filter(jobs, search)


_MUSE_CATEGORY_MAP = {
    "data": "Data Science",
    "data science": "Data Science",
    "data scientist": "Data Science",
    "machine learning": "Data Science",
    "ml engineer": "Data Science",
    "ai": "Data Science",
    "data analyst": "Data Science",
    "data engineer": "Data Science",
    "data engineering": "Data Science",
    "software": "Software Engineering",
    "software engineer": "Software Engineering",
    "backend": "Software Engineering",
    "frontend": "Software Engineering",
    "fullstack": "Software Engineering",
}


def _fetch_themuse(search: FreeApiSearch) -> list[JobListing]:
    params: dict[str, Any] = {"page": max(0, (search.page or 1) - 1)}
    # The Muse expects exact category labels; map common queries; otherwise omit.
    if search.query:
        normalized = search.query.casefold().strip()
        for key, label in _MUSE_CATEGORY_MAP.items():
            if key in normalized:
                params["category"] = label
                break
    if search.location:
        # Pass through known city names; The Muse uses "City, Country" style.
        params["location"] = search.location
    data = _fetch_json(search, "https://www.themuse.com/api/public/jobs", params=params)
    items = data.get("results", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _strip_html(item.get("contents") or "")
        company_info = item.get("company") or {}
        company = company_info.get("name") if isinstance(company_info, dict) else None
        locations = _string_list([loc.get("name") for loc in (item.get("locations") or []) if isinstance(loc, dict)])
        cats = _string_list([cat.get("name") for cat in (item.get("categories") or []) if isinstance(cat, dict)])
        tags = _string_list([tag.get("name") for tag in (item.get("tags") or []) if isinstance(tag, dict)])
        location = ", ".join(locations) or None
        url = (item.get("refs") or {}).get("landing_page") if isinstance(item.get("refs"), dict) else None
        remote = bool(locations) and any("remote" in (loc or "").lower() for loc in locations)
        jobs.append(_make_job(
            source="api:themuse",
            source_url=url,
            apply_url=url,
            raw_text=_join_nonempty(item.get("name"), company, location, desc, " ".join(cats + tags)),
            title=item.get("name") or "[To Be Parsed]",
            company=company or "[To Be Parsed]",
            location=location,
            remote=remote,
            work_mode="remote" if remote else None,
            job_type=item.get("type"),
            description=desc,
            tech_stack=cats + tags,
            posted_date=item.get("publication_date"),
        ))
    return _post_filter(jobs, search)


def _fetch_recruitee(search: FreeApiSearch) -> list[JobListing]:
    if not search.board:
        raise FreeApiError(
            "recruitee requires --board with the company slug. Example: recruitee --board mycompany"
        )
    data = _fetch_json(search, f"https://{search.board}.recruitee.com/api/offers/")
    items = data.get("offers", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _strip_html(item.get("description") or item.get("requirements") or "")
        tags = _string_list(item.get("tags"))
        location = item.get("location") or _first_nonempty(item.get("city"), item.get("country"))
        url = item.get("careers_url") or item.get("url")
        jobs.append(_make_job(
            source="api:recruitee",
            source_url=url,
            apply_url=url,
            raw_text=_join_nonempty(item.get("title"), search.board, location, desc, " ".join(tags)),
            title=item.get("title") or "[To Be Parsed]",
            company=search.board,
            location=location,
            remote=str(item.get("remote") or "").lower() in {"true", "yes"} or "remote" in (str(location or "").lower()),
            work_mode=item.get("employment_type_code"),
            job_type=item.get("employment_type"),
            description=desc,
            tech_stack=tags + _string_list(item.get("department")),
            posted_date=item.get("created_at") or item.get("published_at"),
        ))
    return _post_filter(jobs, search)


def _fetch_smartrecruiters(search: FreeApiSearch) -> list[JobListing]:
    if not search.board:
        raise FreeApiError(
            "smartrecruiters requires --board with the company slug. Example: smartrecruiters --board examplecompany"
        )
    params: dict[str, Any] = {"limit": min(_bounded_limit(search.limit), 100)}
    if search.query:
        params["q"] = search.query
    if search.location:
        params["city"] = search.location
    data = _fetch_json(
        search,
        f"https://api.smartrecruiters.com/v1/companies/{search.board}/postings",
        params=params,
    )
    items = data.get("content", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        location_info = item.get("location") or {}
        location = ""
        if isinstance(location_info, dict):
            location = ", ".join(p for p in [location_info.get("city"), location_info.get("region"), location_info.get("country")] if p)
        url = (item.get("ref") or {}).get("postingUrl") if isinstance(item.get("ref"), dict) else None
        if not url:
            url = item.get("ad", {}).get("url") if isinstance(item.get("ad"), dict) else None
        desc = _strip_html((item.get("jobAd") or {}).get("sections", {}).get("jobDescription", {}).get("text") if isinstance(item.get("jobAd"), dict) else "")
        if not desc:
            desc = _strip_html(item.get("description") or "")
        department = (item.get("department") or {}).get("label") if isinstance(item.get("department"), dict) else None
        function = (item.get("function") or {}).get("label") if isinstance(item.get("function"), dict) else None
        jobs.append(_make_job(
            source="api:smartrecruiters",
            source_url=url,
            apply_url=url,
            raw_text=_join_nonempty(item.get("name"), search.board, location, desc, department, function),
            title=item.get("name") or "[To Be Parsed]",
            company=search.board,
            location=location or None,
            remote="remote" in (location.lower() + " " + (desc or "").lower()),
            description=desc,
            tech_stack=[t for t in [department, function] if t],
            posted_date=item.get("releasedDate") or item.get("createdOn"),
        ))
    return _post_filter(jobs, search)


def _fetch_workable(search: FreeApiSearch) -> list[JobListing]:
    if not search.board:
        raise FreeApiError(
            "workable requires --board with the account slug. Example: workable --board examplecompany"
        )
    data = _fetch_json(
        search,
        f"https://apply.workable.com/api/v1/accounts/{search.board}/jobs",
        params={"limit": _bounded_limit(search.limit)},
    )
    items = data.get("results", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        location_info = item.get("location") or {}
        location = ""
        if isinstance(location_info, dict):
            location = ", ".join(p for p in [location_info.get("city"), location_info.get("region"), location_info.get("country")] if p)
        url = item.get("url") or item.get("application_url")
        desc = _strip_html(item.get("description") or "")
        department = item.get("department")
        jobs.append(_make_job(
            source="api:workable",
            source_url=url,
            apply_url=url,
            raw_text=_join_nonempty(item.get("title"), search.board, location, desc, department),
            title=item.get("title") or "[To Be Parsed]",
            company=search.board,
            location=location or None,
            remote=bool(item.get("remote")) or "remote" in (location.lower() + " " + (desc or "").lower()),
            description=desc,
            tech_stack=[d for d in [department] if d],
            posted_date=item.get("published"),
        ))
    return _post_filter(jobs, search)


def _fetch_personio(search: FreeApiSearch) -> list[JobListing]:
    if not search.board:
        raise FreeApiError(
            "personio requires --board with the company subdomain. Example: personio --board examplecompany"
        )
    url = f"https://{search.board}.jobs.personio.com/xml"
    clean_params = {}  # noqa: F841
    headers = {**HEADERS, "Accept": "application/xml,text/xml,*/*"}
    response = requests.get(url, headers=headers, timeout=search.timeout)
    response.raise_for_status()
    xml_text = response.text
    # Lightweight XML parsing (Personio feeds are small).
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FreeApiError(f"Personio XML parse error for {search.board}: {exc}")
    positions = list(root.iter("position"))
    jobs: list[JobListing] = []
    for position in positions[: _bounded_limit(search.limit)]:
        def _field(tag: str) -> str:
            el = position.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""
        title = _field("name") or "[To Be Parsed]"
        location = _field("office") or _field("city")
        department = _field("department")
        recruiting_category = _field("recruitingCategory")
        employment_type = _field("employmentType")
        desc_parts: list[str] = []
        for jd in position.iter("jobDescriptions"):
            for d in jd.iter("jobDescription"):
                name = d.find("name")
                value = d.find("value")
                if name is not None and value is not None and value.text:
                    desc_parts.append((name.text or "").strip() + ": " + _strip_html(value.text))
        desc = "\n\n".join(desc_parts)
        post_id = _field("id")
        public_url = f"https://{search.board}.jobs.personio.com/job/{post_id}" if post_id else None
        jobs.append(_make_job(
            source="api:personio",
            source_url=public_url,
            apply_url=public_url,
            raw_text=_join_nonempty(title, search.board, location, desc, department, recruiting_category),
            title=title,
            company=search.board,
            location=location or None,
            remote="remote" in (location.lower() + " " + (desc or "").lower()),
            job_type=employment_type or None,
            description=desc,
            tech_stack=[t for t in [department, recruiting_category] if t],
            posted_date=_field("createdAt"),
        ))
    return _post_filter(jobs, search)


_PARIS_LOC_KEYS = {"", "paris", "paris 75", "75"}
_IDF_LOC_KEYS = {"ile-de-france", "île-de-france", "idf", "ile de france", "île de france", "11"}
_FRANCE_LOC_KEYS = {"france", "fr", "national"}


def _france_location_params(search: FreeApiSearch) -> dict[str, Any]:
    """Map user-facing location to France Travail API parameters.

    The /offres/search endpoint accepts ``departement``, ``region``, OR
    ``commune`` + ``distance`` — but the ``commune+distance`` pair regularly
    returns HTTP 400 in production for valid Paris codes. We default to the
    reliable ``departement`` filter for Paris and only emit ``commune+
    distance`` when the caller explicitly opted into a radius via the search
    options AND the location is single-commune. The radius is also clamped
    into 5–50 km, which is what the FT web UI itself allows.
    """
    loc = (search.location or search.country or "").strip().casefold()
    params: dict[str, Any] = {}
    radius = max(0, min(int(getattr(search, "radius_km", None) or 0), 50))
    if loc in _PARIS_LOC_KEYS:
        if 5 <= radius <= 50:
            params["commune"] = "75056"
            params["distance"] = str(radius)
        else:
            params["departement"] = "75"
    elif loc in _IDF_LOC_KEYS:
        params["region"] = "11"
    elif loc in _FRANCE_LOC_KEYS:
        # No filter — search nationally.
        pass
    elif re.fullmatch(r"\d{2,3}", loc):
        params["departement"] = loc
    else:
        params["motsClesLocationHint"] = search.location
    return params


def _france_travail_apply_url(item: dict[str, Any]) -> str | None:
    origine = item.get("origineOffre") or {}
    if isinstance(origine, dict):
        for key in ("urlOrigine", "url", "urlPostulation"):
            if origine.get(key):
                return str(origine[key])
    if item.get("url"):
        return str(item["url"])
    if item.get("id"):
        return "https://candidat.francetravail.fr/offres/recherche/detail/" + str(item["id"])
    return None


def _ft_request(url: str, params: dict[str, Any], search: FreeApiSearch, token: str) -> Any:
    """Call the FT search endpoint with retry semantics.

    Retries:
    - 401: invalidate the cached token, mint a fresh one, retry once.
    - 400 when ``commune+distance`` was set: drop the radius pair, fall back
      to ``departement`` if available, and retry once. (FT's 400s on this
      combo are common with valid INSEE codes.)
    """
    def _call(extra_headers: dict[str, str]) -> Any:
        return _get_json(
            url,
            params=params,
            timeout=search.timeout,
            extra_headers=extra_headers,
            use_cache=False,
            cache_ttl_hours=0,
        )

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        return _call(headers)
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (401, 403):
            invalidate_france_travail_token_cache()
            fresh = france_travail_token(
                timeout=search.timeout,
                use_cache=search.use_cache,
                cache_ttl_hours=search.cache_ttl_hours,
            )
            headers = {"Authorization": f"Bearer {fresh}", "Accept": "application/json"}
            return _call(headers)
        if status == 400 and "commune" in params and "distance" in params:
            params.pop("commune", None)
            params.pop("distance", None)
            params.setdefault("departement", "75")
            return _call(headers)
        raise


def _fetch_francetravail(search: FreeApiSearch) -> list[JobListing]:
    try:
        token = france_travail_token(
            timeout=search.timeout,
            use_cache=search.use_cache,
            cache_ttl_hours=search.cache_ttl_hours,
        )
    except ValueError as exc:
        raise FreeApiError(
            "francetravail requires free France Travail API credentials. Set "
            "FRANCE_TRAVAIL_CLIENT_ID and FRANCE_TRAVAIL_CLIENT_SECRET after requesting access."
        ) from exc
    base_url = france_travail_env("FRANCE_TRAVAIL_API_BASE_URL", "https://api.francetravail.io")
    url = base_url.rstrip("/") + "/partenaire/offresdemploi/v2/offres/search"
    per_page = min(_bounded_limit(search.limit), 50)
    start = max(0, (max(1, search.page) - 1) * per_page)
    end = start + per_page - 1
    params: dict[str, Any] = {
        "motsCles": search.query or "data science",
        "range": f"{start}-{end}",
    }
    loc_params = _france_location_params(search)
    location_hint = loc_params.pop("motsClesLocationHint", "")
    params.update(loc_params)
    if location_hint:
        params["motsCles"] = f"{params['motsCles']} {location_hint}".strip()
    # Make sure we never end up with both commune and departement (FT rejects it).
    if "commune" in params and "departement" in params:
        params.pop("departement", None)
    try:
        data = _ft_request(url, params, search, token)
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", "?")
        raise FreeApiError(
            f"France Travail returned HTTP {status} for query '{params.get('motsCles')}'. "
            "Check credentials, scopes, and that the API client is approved for v2/offres."
        ) from exc
    items = data.get("resultats", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entreprise = item.get("entreprise") if isinstance(item.get("entreprise"), dict) else {}
        lieu = item.get("lieuTravail") if isinstance(item.get("lieuTravail"), dict) else {}
        salaire = item.get("salaire") if isinstance(item.get("salaire"), dict) else {}
        competences = item.get("competences") if isinstance(item.get("competences"), list) else []
        skills = []
        for comp in competences:
            if isinstance(comp, dict) and comp.get("libelle"):
                skills.append(str(comp["libelle"]))
        location = str(lieu.get("libelle") or lieu.get("commune") or "").strip() or None
        desc = _strip_html(_join_nonempty(
            item.get("description"),
            item.get("profilRecherche"),
            item.get("experienceLibelle"),
            item.get("qualificationLibelle"),
            salaire.get("libelle") or salaire.get("commentaire"),
        ))
        apply_url = _france_travail_apply_url(item)
        jobs.append(_make_job(
            source="api:francetravail",
            source_url=apply_url,
            apply_url=apply_url,
            raw_text=_join_nonempty(item.get("intitule"), entreprise.get("nom"), location, desc, " ".join(skills)),
            title=item.get("intitule") or "[To Be Parsed]",
            company=entreprise.get("nom") or "France Travail",
            location=location,
            remote="télétravail" in desc.casefold() or "teletravail" in desc.casefold() or "remote" in desc.casefold(),
            work_mode="remote" if ("télétravail" in desc.casefold() or "teletravail" in desc.casefold()) else None,
            job_type=item.get("typeContratLibelle") or item.get("typeContrat"),
            salary_currency="EUR",
            description=desc,
            requirements=_string_list(item.get("qualitesProfessionnelles")),
            responsibilities=[],
            tech_stack=skills,
            posted_date=item.get("dateCreation") or item.get("dateActualisation"),
        ))
    return _post_filter(jobs, search)


_LBA_IDF_DEPARTMENTS = ["75", "77", "78", "91", "92", "93", "94", "95"]
_LBA_QUERY_ROMES = {
    "data": ["M1403", "M1805", "M1806"],
    "scientist": ["M1403", "M1805"],
    "science": ["M1403", "M1805"],
    "analyst": ["M1403", "M1805"],
    "analyste": ["M1403", "M1805"],
    "engineer": ["M1805", "M1806"],
    "ingénieur": ["M1805", "M1806"],
    "ingenieur": ["M1805", "M1806"],
    "machine": ["M1805", "M1806"],
    "learning": ["M1805", "M1806"],
    "ml": ["M1805", "M1806"],
    "ai": ["M1805", "M1806"],
    "ia": ["M1805", "M1806"],
    "bi": ["M1403", "M1805"],
}


def _lba_token() -> str:
    load_local_env()
    token = os.environ.get("APPRENTISSAGE_API_TOKEN") or os.environ.get("LABONNEALTERNANCE_API_TOKEN")
    if not token:
        raise FreeApiError(
            "labonnealternance requires APPRENTISSAGE_API_TOKEN in .env.local. "
            "The token is local-only and must not be committed."
        )
    return token


def _lba_departements(location: str) -> list[str]:
    key = (location or "").strip().casefold()
    if key in {"", "paris", "75", "paris 75"}:
        return ["75"]
    if key in {"ile-de-france", "île-de-france", "ile de france", "île de france", "idf", "11"}:
        return _LBA_IDF_DEPARTMENTS
    if re.fullmatch(r"\d{2,3}", key):
        return [key]
    if key in {"france", "fr", "national"}:
        return []
    return ["75"] if "paris" in key else []


def _lba_romes(query: str) -> list[str]:
    romes: list[str] = []
    for token in re.split(r"[\s,;/+.-]+", (query or "").casefold()):
        for code in _LBA_QUERY_ROMES.get(token, []):
            if code not in romes:
                romes.append(code)
    return romes[:6]


def _fetch_labonnealternance(search: FreeApiSearch) -> list[JobListing]:
    token = _lba_token()
    base_url = os.environ.get("APPRENTISSAGE_API_BASE_URL", "https://api.apprentissage.beta.gouv.fr")
    url = base_url.rstrip("/") + "/api/job/v1/search"
    params: dict[str, Any] = {
        "job_name": search.query or "data",
        "radius": min(max(int(search.radius_km or 30), 0), 200),
    }
    departments = _lba_departements(search.location)
    if departments:
        params["departements"] = departments
    romes = _lba_romes(search.query)
    if romes:
        params["romes"] = ",".join(romes)
    data = _fetch_json(
        search,
        url,
        params=params,
        extra_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    items = data.get("jobs", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    seen_lba: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = item.get("identifier") if isinstance(item.get("identifier"), dict) else {}
        offer = item.get("offer") if isinstance(item.get("offer"), dict) else {}
        workplace = item.get("workplace") if isinstance(item.get("workplace"), dict) else {}
        contract = item.get("contract") if isinstance(item.get("contract"), dict) else {}
        apply = item.get("apply") if isinstance(item.get("apply"), dict) else {}
        publication = offer.get("publication") if isinstance(offer.get("publication"), dict) else {}
        location_data = workplace.get("location") if isinstance(workplace.get("location"), dict) else {}
        domain = workplace.get("domain") if isinstance(workplace.get("domain"), dict) else {}
        naf = domain.get("naf") if isinstance(domain.get("naf"), dict) else {}
        desired = _string_list(offer.get("desired_skills"))
        acquired = _string_list(offer.get("to_be_acquired_skills"))
        access = _string_list(offer.get("access_conditions"))
        rome_codes = _string_list(offer.get("rome_codes"))
        company = _first_nonempty(workplace.get("brand"), workplace.get("name"), workplace.get("legal_name"), "La bonne alternance")
        location = _first_nonempty(location_data.get("address"), workplace.get("address"))
        desc = _strip_html(_join_nonempty(
            offer.get("description"),
            workplace.get("description"),
            "\n".join(desired),
            "\n".join(acquired[:10]),
            "\n".join(access),
            naf.get("label"),
        ))
        contract_types = _string_list(contract.get("type"))
        remote_raw = str(contract.get("remote") or "").casefold()
        apply_url = _first_nonempty(apply.get("url"), workplace.get("website"))
        identifier_id = _first_nonempty(identifier.get("id"), identifier.get("partner_job_id"))
        dedupe_key = (apply_url or identifier_id or (str(offer.get("title") or "") + "|" + company + "|" + location)).casefold()
        if dedupe_key in seen_lba:
            continue
        seen_lba.add(dedupe_key)
        jobs.append(_make_job(
            source="api:labonnealternance",
            source_url=apply_url or (f"https://labonnealternance.apprentissage.beta.gouv.fr/emploi/{identifier_id}" if identifier_id else None),
            apply_url=apply_url or None,
            raw_text=_join_nonempty(offer.get("title"), company, location, desc, " ".join(rome_codes)),
            title=offer.get("title") or "[To Be Parsed]",
            company=company,
            location=location or None,
            remote=remote_raw in {"true", "remote", "teletravail", "télétravail"} or "télétravail" in desc.casefold(),
            work_mode=contract.get("remote") or None,
            job_type=", ".join(contract_types) if contract_types else "Alternance",
            salary_currency="EUR",
            description=desc,
            requirements=desired + access,
            responsibilities=[],
            tech_stack=desired + acquired[:12] + rome_codes,
            benefits=[],
            posted_date=publication.get("creation"),
            deadline=publication.get("expiration"),
        ))
    strict = _post_filter(jobs, search, apply_query_filter=True)
    if strict:
        return strict
    return _post_filter(jobs, search, apply_query_filter=False)


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


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


_FETCHERS: dict[str, Callable[[FreeApiSearch], list[JobListing]]] = {
    "remotive": _fetch_remotive,
    "remoteok": _fetch_remoteok,
    "himalayas": _fetch_himalayas,
    "arbeitnow": _fetch_arbeitnow,
    "jobicy": _fetch_jobicy,
    "themuse": _fetch_themuse,
    "greenhouse": _fetch_greenhouse,
    "lever": _fetch_lever,
    "ashby": _fetch_ashby,
    "recruitee": _fetch_recruitee,
    "smartrecruiters": _fetch_smartrecruiters,
    "workable": _fetch_workable,
    "personio": _fetch_personio,
    "francetravail": _fetch_francetravail,
    "labonnealternance": _fetch_labonnealternance,
}


def search_free_api_jobs(
    source: str,
    *,
    query: str = "",
    location: str = "",
    country: str = "",
    board: str = "",
    limit: int = 20,
    page: int = 1,
    remote_only: bool = False,
    internships_only: bool = False,
    min_relevance: int = 0,
    france_eu_only: bool = False,
    radius_km: int = 0,
    timeout: int = DEFAULT_TIMEOUT,
    use_cache: bool = False,
    cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
) -> list[JobListing]:
    """Fetch public jobs from a free/read-only job source.

    The function returns normalized :class:`JobListing` instances. It does not
    persist anything; use ``add_job_to_tracker`` when the caller explicitly asks
    to save results.
    """
    canonical = canonical_source(source)
    info = SUPPORTED_SOURCES[canonical]
    if info.requires_board and not board.strip():
        raise FreeApiError(f"{canonical} requires --board ({info.board_label}).")
    search = FreeApiSearch(
        source=canonical,
        query=query.strip(),
        location=location.strip(),
        country=country.strip(),
        board=board.strip(),
        limit=_bounded_limit(limit),
        page=max(1, int(page or 1)),
        remote_only=remote_only,
        internships_only=internships_only,
        min_relevance=max(0, min(int(min_relevance or 0), 100)),
        france_eu_only=france_eu_only,
        radius_km=max(0, min(int(radius_km or 0), 100)),
        timeout=timeout,
        use_cache=use_cache,
        cache_ttl_hours=cache_ttl_hours,
    )
    return _FETCHERS[canonical](search)


# Sources that work without board configuration. Credentialed sources in this
# list fail softly inside search_all_free_sources when their local token is not
# configured.
KEYWORD_ONLY_SOURCES: tuple[str, ...] = (
    "remotive",
    "remoteok",
    "himalayas",
    "arbeitnow",
    "jobicy",
    "themuse",
    "labonnealternance",
)


def search_all_free_sources(
    *,
    query: str = "",
    location: str = "",
    country: str = "",
    limit_per_source: int = 10,
    remote_only: bool = False,
    internships_only: bool = False,
    min_relevance: int = 0,
    france_eu_only: bool = False,
    radius_km: int = 0,
    sources: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    use_cache: bool = True,
    cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
) -> dict[str, Any]:
    """Search several keyword-only public APIs in one shot.

    Returns a dict containing ``jobs`` (combined deduplicated list),
    ``per_source`` (per-source counts), and ``errors`` (per-source error
    messages). Failures in any single source don't break the rest.
    """
    chosen = sources or list(KEYWORD_ONLY_SOURCES)
    seen_keys: set[str] = set()
    combined: list[JobListing] = []
    per_source: dict[str, int] = {}
    errors: dict[str, str] = {}
    for source in chosen:
        try:
            results = search_free_api_jobs(
                source,
                query=query,
                location=location,
                country=country,
                limit=limit_per_source,
                remote_only=remote_only,
                internships_only=internships_only,
                min_relevance=min_relevance,
                france_eu_only=france_eu_only,
                radius_km=radius_km,
                timeout=timeout,
                use_cache=use_cache,
                cache_ttl_hours=cache_ttl_hours,
            )
        except FreeApiError as exc:
            errors[source] = str(exc)
            per_source[source] = 0
            continue
        except Exception as exc:
            errors[source] = f"{type(exc).__name__}: {exc}"
            per_source[source] = 0
            continue
        per_source[source] = len(results)
        for job in results:
            key = (
                (job.apply_url or job.source_url or "").strip().casefold()
                or (job.title.casefold() + "|" + job.company.casefold())
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            combined.append(job)
    return {"jobs": combined, "per_source": per_source, "errors": errors}
