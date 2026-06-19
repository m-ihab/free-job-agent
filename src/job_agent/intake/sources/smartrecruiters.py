"""SmartRecruiters public postings API connector."""
from __future__ import annotations

from typing import Any

from job_agent.schemas.job import JobListing

from .base import (
    FreeApiError,
    FreeApiSearch,
    _bounded_limit,
    _fetch_json,
    _join_nonempty,
    _make_job,
    _post_filter,
    _strip_html,
)


def fetch(search: FreeApiSearch) -> list[JobListing]:
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
