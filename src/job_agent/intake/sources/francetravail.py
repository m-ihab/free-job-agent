"""France Travail Offres d'emploi API connector (free habilitation credentials)."""
from __future__ import annotations

import re
from typing import Any

from job_agent.intake.france_travail_auth import (
    france_travail_env,
    france_travail_token,
    invalidate_france_travail_token_cache,
)
from job_agent.schemas.job import JobListing

from . import base
from .base import (
    _CONTRACT_TYPE_FT,
    FreeApiError,
    FreeApiSearch,
    _as_dict,
    _as_list,
    _bounded_limit,
    _get_json,
    _join_nonempty,
    _make_job,
    _post_filter,
    _string_list,
    _strip_html,
)

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
    except base.requests.HTTPError as exc:
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


def fetch(search: FreeApiSearch) -> list[JobListing]:
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
    # Contract type filter at API level — narrows results before post-filter.
    ct = (search.contract_type or "").strip().lower()
    if not ct and search.internships_only:
        ct = "stage_and_alternance"
    if ct in _CONTRACT_TYPE_FT:
        params["typeContrat"] = _CONTRACT_TYPE_FT[ct]
    try:
        data = _ft_request(url, params, search, token)
    except base.requests.HTTPError as exc:
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
        entreprise = _as_dict(item.get("entreprise"))
        lieu = _as_dict(item.get("lieuTravail"))
        salaire = _as_dict(item.get("salaire"))
        competences = _as_list(item.get("competences"))
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
