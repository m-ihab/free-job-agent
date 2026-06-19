"""Arbeitnow free Europe/remote job board API connector."""
from __future__ import annotations

from typing import Any

from job_agent.schemas.job import JobListing

from .base import (
    FreeApiSearch,
    _fetch_json,
    _join_nonempty,
    _make_job,
    _post_filter,
    _string_list,
    _strip_html,
)


def fetch(search: FreeApiSearch) -> list[JobListing]:
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
