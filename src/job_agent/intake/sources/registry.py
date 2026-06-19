"""Source registry and dispatch for free/public job-source APIs.

Holds the supported-source catalogue, alias resolution, the fetcher registry,
and the public dispatch functions :func:`search_free_api_jobs` and
:func:`search_all_free_sources`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from job_agent.schemas.job import JobListing

from . import (
    arbeitnow,
    ashby,
    francetravail,
    greenhouse,
    himalayas,
    jobicy,
    labonnealternance,
    lever,
    personio,
    recruitee,
    remoteok,
    remotive,
    smartrecruiters,
    themuse,
    workable,
)
from .base import (
    DEFAULT_CACHE_TTL_HOURS,
    DEFAULT_TIMEOUT,
    FreeApiError,
    FreeApiSearch,
    SourceClient,
    SourceInfo,
    _bounded_limit,
)

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


_FETCHERS: dict[str, SourceClient] = {
    "remotive": remotive.fetch,
    "remoteok": remoteok.fetch,
    "himalayas": himalayas.fetch,
    "arbeitnow": arbeitnow.fetch,
    "jobicy": jobicy.fetch,
    "themuse": themuse.fetch,
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "recruitee": recruitee.fetch,
    "smartrecruiters": smartrecruiters.fetch,
    "workable": workable.fetch,
    "personio": personio.fetch,
    "francetravail": francetravail.fetch,
    "labonnealternance": labonnealternance.fetch,
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


@dataclass(frozen=True)
class FreeApiSearchParams:
    """Internal plumbing object for a single-source public job search.

    Collapses the many keyword arguments of :func:`search_free_api_jobs` into a
    single value object. The public function keeps its explicit signature and
    builds this internally.
    """

    source: str
    query: str = ""
    location: str = ""
    country: str = ""
    board: str = ""
    limit: int = 20
    page: int = 1
    remote_only: bool = False
    internships_only: bool = False
    contract_type: str = ""
    min_relevance: int = 0
    france_eu_only: bool = False
    radius_km: int = 0
    timeout: int = DEFAULT_TIMEOUT
    use_cache: bool = False
    cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS


def _run_search(params: FreeApiSearchParams) -> list[JobListing]:
    """Resolve the source, validate board requirements, and dispatch."""
    canonical = canonical_source(params.source)
    info = SUPPORTED_SOURCES[canonical]
    if info.requires_board and not params.board.strip():
        raise FreeApiError(f"{canonical} requires --board ({info.board_label}).")
    search = FreeApiSearch(
        source=canonical,
        query=params.query.strip(),
        location=params.location.strip(),
        country=params.country.strip(),
        board=params.board.strip(),
        limit=_bounded_limit(params.limit),
        page=max(1, int(params.page or 1)),
        remote_only=params.remote_only,
        internships_only=params.internships_only,
        contract_type=params.contract_type.strip().lower(),
        min_relevance=max(0, min(int(params.min_relevance or 0), 100)),
        france_eu_only=params.france_eu_only,
        radius_km=max(0, min(int(params.radius_km or 0), 100)),
        timeout=params.timeout,
        use_cache=params.use_cache,
        cache_ttl_hours=params.cache_ttl_hours,
    )
    return _FETCHERS[canonical](search)


def search_free_api_jobs(  # noqa: PLR0913 — public API boundary; plumbing lives in FreeApiSearchParams
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
    contract_type: str = "",
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
    return _run_search(FreeApiSearchParams(
        source=source,
        query=query,
        location=location,
        country=country,
        board=board,
        limit=limit,
        page=page,
        remote_only=remote_only,
        internships_only=internships_only,
        contract_type=contract_type,
        min_relevance=min_relevance,
        france_eu_only=france_eu_only,
        radius_km=radius_km,
        timeout=timeout,
        use_cache=use_cache,
        cache_ttl_hours=cache_ttl_hours,
    ))


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


@dataclass(frozen=True)
class FreeApiMultiSearchParams:
    """Internal plumbing object for a multi-source public job search."""

    query: str = ""
    location: str = ""
    country: str = ""
    limit_per_source: int = 10
    remote_only: bool = False
    internships_only: bool = False
    contract_type: str = ""
    min_relevance: int = 0
    france_eu_only: bool = False
    radius_km: int = 0
    sources: list[str] | None = None
    timeout: int = DEFAULT_TIMEOUT
    use_cache: bool = True
    cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS


def _run_multi_search(opts: FreeApiMultiSearchParams) -> dict[str, Any]:
    chosen = opts.sources or list(KEYWORD_ONLY_SOURCES)
    seen_keys: set[str] = set()
    combined: list[JobListing] = []
    per_source: dict[str, int] = {}
    errors: dict[str, str] = {}
    for source in chosen:
        try:
            results = search_free_api_jobs(
                source,
                query=opts.query,
                location=opts.location,
                country=opts.country,
                limit=opts.limit_per_source,
                remote_only=opts.remote_only,
                internships_only=opts.internships_only,
                contract_type=opts.contract_type,
                min_relevance=opts.min_relevance,
                france_eu_only=opts.france_eu_only,
                radius_km=opts.radius_km,
                timeout=opts.timeout,
                use_cache=opts.use_cache,
                cache_ttl_hours=opts.cache_ttl_hours,
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


def search_all_free_sources(  # noqa: PLR0913 — public API boundary; plumbing lives in FreeApiMultiSearchParams
    *,
    query: str = "",
    location: str = "",
    country: str = "",
    limit_per_source: int = 10,
    remote_only: bool = False,
    internships_only: bool = False,
    contract_type: str = "",
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
    return _run_multi_search(FreeApiMultiSearchParams(
        query=query,
        location=location,
        country=country,
        limit_per_source=limit_per_source,
        remote_only=remote_only,
        internships_only=internships_only,
        contract_type=contract_type,
        min_relevance=min_relevance,
        france_eu_only=france_eu_only,
        radius_km=radius_km,
        sources=sources,
        timeout=timeout,
        use_cache=use_cache,
        cache_ttl_hours=cache_ttl_hours,
    ))
