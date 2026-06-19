"""Greenhouse public Job Board API connector."""
from __future__ import annotations

from job_agent.schemas.job import JobListing

from .base import (
    FreeApiError,
    FreeApiSearch,
    _fetch_json,
    _join_nonempty,
    _make_job,
    _post_filter,
    _string_list,
    _strip_html,
)


def fetch(search: FreeApiSearch) -> list[JobListing]:
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
