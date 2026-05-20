"""Free/public job-source API ingestion.

These connectors are intentionally read-only. They fetch public job postings from
sources that expose unauthenticated JSON feeds, free-key APIs, or public ATS
job-board feeds and normalize them into :class:`JobListing` objects. They do not
create accounts, log in, bypass access controls, or submit applications.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from job_agent.intake.url import HEADERS
from job_agent.normalizer import normalize
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
    "greenhouse": SourceInfo("greenhouse", "Greenhouse public Job Board API", True, "Greenhouse board token"),
    "lever": SourceInfo("lever", "Lever public Postings API", True, "Lever site slug"),
    "ashby": SourceInfo("ashby", "Ashby public Job Postings API", True, "Ashby job board name"),
    "francetravail": SourceInfo(
        "francetravail",
        "France Travail Offres d'emploi API; free habilitation credentials required",
        requires_env=("FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET"),
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


def _cache_dir() -> Path:
    return Path(os.environ.get("JOB_AGENT_API_CACHE_DIR") or (Path.home() / ".job_agent" / "api_cache"))


def _cache_key(url: str, params: dict[str, Any] | None) -> str:
    payload = json.dumps({"url": url, "params": params or {}}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest() + ".json"


def _read_cached_json(url: str, params: dict[str, Any] | None, ttl_hours: float) -> Any | None:
    if ttl_hours <= 0:
        return None
    path = _cache_dir() / _cache_key(url, params)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl_hours * 3600:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cached_json(url: str, params: dict[str, Any] | None, payload: Any) -> None:
    try:
        cache_dir = _cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / _cache_key(url, params)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # Cache failures should never break job search.
        return


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
        cached = _read_cached_json(url, clean_params, cache_ttl_hours)
        if cached is not None:
            return cached
    headers = {**HEADERS, **(extra_headers or {})}
    response = requests.get(url, params=clean_params, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if use_cache:
        _write_cached_json(url, clean_params, payload)
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


def _contains_query(job: JobListing, query: str) -> bool:
    if not query.strip():
        return True
    haystack = "\n".join([
        job.title,
        job.company,
        job.location or "",
        job.description or "",
        job.raw_text or "",
        " ".join(job.tech_stack),
    ]).casefold()
    tokens = [t for t in re.split(r"\s+", query.casefold().strip()) if len(t) >= 2]
    return all(token in haystack for token in tokens)


def _contains_location(job: JobListing, location: str) -> bool:
    if not location.strip():
        return True
    if job.remote and location.strip().casefold() in {"remote", "worldwide", "anywhere"}:
        return True
    haystack = "\n".join([job.location or "", job.description or "", job.raw_text or ""]).casefold()
    return location.casefold().strip() in haystack


def _post_filter(jobs: list[JobListing], search: FreeApiSearch) -> list[JobListing]:
    result: list[JobListing] = []
    for job in jobs:
        if search.remote_only and not job.remote:
            continue
        if not _contains_query(job, search.query):
            continue
        if not _contains_location(job, search.location):
            continue
        result.append(job)
        if len(result) >= _bounded_limit(search.limit):
            break
    return result


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


def _france_travail_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _france_travail_token(search: FreeApiSearch) -> str:
    client_id = _france_travail_env("FRANCE_TRAVAIL_CLIENT_ID")
    client_secret = _france_travail_env("FRANCE_TRAVAIL_CLIENT_SECRET")
    scope = _france_travail_env("FRANCE_TRAVAIL_SCOPE", "api_offresdemploiv2 o2dsoffre")
    token_url = _france_travail_env(
        "FRANCE_TRAVAIL_TOKEN_URL",
        "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire",
    )
    if not client_id or not client_secret:
        raise FreeApiError(
            "francetravail requires free France Travail API credentials. Set "
            "FRANCE_TRAVAIL_CLIENT_ID and FRANCE_TRAVAIL_CLIENT_SECRET after requesting access."
        )
    cache_params = {"client_id": client_id, "scope": scope, "kind": "oauth_token"}
    if search.use_cache:
        cached = _read_cached_json(token_url, cache_params, min(search.cache_ttl_hours, 0.75))
        if isinstance(cached, dict) and cached.get("access_token"):
            return str(cached["access_token"])
    response = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        },
        timeout=search.timeout,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise FreeApiError("France Travail OAuth response did not contain access_token")
    if search.use_cache:
        _write_cached_json(token_url, cache_params, {"access_token": token})
    return str(token)


def _france_location_params(search: FreeApiSearch) -> dict[str, Any]:
    loc = (search.location or search.country or "").strip().casefold()
    params: dict[str, Any] = {}
    # France Travail supports department filters. Paris is department 75; this
    # is the safest default for the user's target market.
    if loc in {"", "paris", "paris 75", "75", "ile-de-france", "île-de-france", "idf"}:
        params["departement"] = "75" if loc in {"", "paris", "paris 75", "75"} else "75"
    elif re.fullmatch(r"\d{2,3}", loc):
        params["departement"] = loc
    else:
        # Keep a human-readable hint in the query when no safe code mapping is known.
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


def _fetch_francetravail(search: FreeApiSearch) -> list[JobListing]:
    token = _france_travail_token(search)
    base_url = _france_travail_env("FRANCE_TRAVAIL_API_BASE_URL", "https://api.francetravail.io")
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
    data = _get_json(
        url,
        params=params,
        timeout=search.timeout,
        extra_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        use_cache=search.use_cache,
        cache_ttl_hours=search.cache_ttl_hours,
    )
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
    "greenhouse": _fetch_greenhouse,
    "lever": _fetch_lever,
    "ashby": _fetch_ashby,
    "francetravail": _fetch_francetravail,
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
        timeout=timeout,
        use_cache=use_cache,
        cache_ttl_hours=cache_ttl_hours,
    )
    return _FETCHERS[canonical](search)
