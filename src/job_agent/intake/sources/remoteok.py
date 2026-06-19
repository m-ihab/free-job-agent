"""Remote OK public JSON feed connector."""
from __future__ import annotations

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
