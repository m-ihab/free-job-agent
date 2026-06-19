"""Recruitee public company offers API connector."""
from __future__ import annotations

from job_agent.schemas.job import JobListing

from .base import (
    FreeApiError,
    FreeApiSearch,
    _fetch_json,
    _first_nonempty,
    _join_nonempty,
    _make_job,
    _post_filter,
    _string_list,
    _strip_html,
)


def fetch(search: FreeApiSearch) -> list[JobListing]:
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
