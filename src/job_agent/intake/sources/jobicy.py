"""Jobicy remote-jobs JSON feed connector."""
from __future__ import annotations

from typing import Any

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
    params: dict[str, Any] = {"count": _bounded_limit(search.limit)}
    location_key = (search.location or search.country or "").strip().casefold()
    geo_map = {
        "france": "france",
        "paris": "france",
        "europe": "europe",
        "united kingdom": "uk",
        "uk": "uk",
        "usa": "usa",
        "united states": "usa",
        "germany": "germany",
        "spain": "spain",
        "italy": "italy",
        "netherlands": "netherlands",
        "anywhere": "anywhere",
        "worldwide": "anywhere",
        "remote": "anywhere",
    }
    geo = geo_map.get(location_key)
    if geo:
        params["geo"] = geo
    if search.query:
        params["tag"] = search.query
    data = _fetch_json(search, "https://jobicy.com/api/v2/remote-jobs", params=params)
    items = data.get("jobs", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _strip_html(item.get("jobDescription") or item.get("jobExcerpt") or "")
        tags = _string_list(item.get("jobIndustry")) + _string_list(item.get("jobType"))
        location = item.get("jobGeo") or "Remote"
        url = item.get("url") or item.get("jobUrl")
        jobs.append(_make_job(
            source="api:jobicy",
            source_url=url,
            apply_url=url,
            raw_text=_join_nonempty(item.get("jobTitle"), item.get("companyName"), location, desc, " ".join(tags)),
            title=item.get("jobTitle") or "[To Be Parsed]",
            company=item.get("companyName") or "[To Be Parsed]",
            location=location,
            remote=True,
            work_mode="remote",
            job_type=", ".join(_string_list(item.get("jobType"))) or None,
            description=desc,
            tech_stack=tags,
            posted_date=item.get("pubDate"),
        ))
    return _post_filter(jobs, search)
