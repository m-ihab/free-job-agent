"""La bonne alternance apprenticeship opportunities API connector."""
from __future__ import annotations

import os
import re
from typing import Any

from job_agent.schemas.job import JobListing
from job_agent.secrets import load_local_env

from .base import (
    FreeApiError,
    FreeApiSearch,
    _as_dict,
    _fetch_json,
    _first_nonempty,
    _join_nonempty,
    _make_job,
    _post_filter,
    _string_list,
    _strip_html,
)

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


def fetch(search: FreeApiSearch) -> list[JobListing]:
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
        identifier = _as_dict(item.get("identifier"))
        offer = _as_dict(item.get("offer"))
        workplace = _as_dict(item.get("workplace"))
        contract = _as_dict(item.get("contract"))
        apply = _as_dict(item.get("apply"))
        publication = _as_dict(offer.get("publication"))
        location_data = _as_dict(workplace.get("location"))
        domain = _as_dict(workplace.get("domain"))
        naf = _as_dict(domain.get("naf"))
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
    # Always keep the query filter on. The previous "recall fallback" re-ran
    # _post_filter with apply_query_filter=False whenever the strict pass was
    # empty, which leaked off-topic apprenticeships (e.g. "Informaticien",
    # "Master SI/Finance Business") into a "data scientist" search. _contains_query
    # already expands FR/EN synonyms, so genuine data alternance/stage offers
    # still pass; returning nothing is better than returning irrelevant rows.
    return _post_filter(jobs, search, apply_query_filter=True)
