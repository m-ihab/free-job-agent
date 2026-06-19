"""Himalayas remote-jobs public JSON API connector."""
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


def _himalayas_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("jobs", "data", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def fetch(search: FreeApiSearch) -> list[JobListing]:
    params: dict[str, Any] = {"q": search.query, "sort": "recent", "page": max(1, search.page)}
    if search.country:
        params["country"] = search.country
    if search.remote_only:
        params["worldwide"] = "true"
    data = _fetch_json(search, "https://himalayas.app/jobs/api/search", params=params)
    jobs: list[JobListing] = []
    for item in _himalayas_items(data):
        desc = _strip_html(item.get("description") or item.get("descriptionHtml") or item.get("excerpt"))
        locations = _string_list(item.get("locationRestrictions") or item.get("locations") or item.get("location"))
        categories = _string_list(item.get("category") or item.get("categories") or item.get("parentCategories"))
        company = item.get("companyName") or item.get("company") or "[To Be Parsed]"
        url = item.get("applicationLink") or item.get("applyUrl") or item.get("jobUrl") or item.get("url")
        jobs.append(_make_job(
            source="api:himalayas",
            source_url=item.get("jobUrl") or url,
            apply_url=url,
            raw_text=_join_nonempty(item.get("title"), company, ", ".join(locations), item.get("excerpt"), desc),
            title=item.get("title") or "[To Be Parsed]",
            company=company,
            location=", ".join(locations) or "Remote",
            remote=True,
            work_mode="remote",
            job_type=item.get("employmentType"),
            salary_min=item.get("minSalary"),
            salary_max=item.get("maxSalary"),
            salary_currency=item.get("currency") or "USD",
            description=desc,
            tech_stack=categories,
            posted_date=item.get("postedAt") or item.get("publishedAt"),
        ))
    return _post_filter(jobs, search)
