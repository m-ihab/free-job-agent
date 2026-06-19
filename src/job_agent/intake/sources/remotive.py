"""Remotive remote-jobs public API connector."""
from __future__ import annotations

from job_agent.schemas.job import JobListing

from .base import (
    FreeApiSearch,
    _bounded_limit,
    _fetch_json,
    _join_nonempty,
    _make_job,
    _post_filter,
    _string_list,
    _strip_html,
)


def fetch(search: FreeApiSearch) -> list[JobListing]:
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
