"""Workable public account jobs API connector."""
from __future__ import annotations

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
