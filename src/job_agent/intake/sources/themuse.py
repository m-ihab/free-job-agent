"""The Muse public jobs API connector."""
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

_MUSE_CATEGORY_MAP = {
    "data": "Data Science",
    "data science": "Data Science",
    "data scientist": "Data Science",
    "machine learning": "Data Science",
    "ml engineer": "Data Science",
    "ai": "Data Science",
    "data analyst": "Data Science",
    "data engineer": "Data Science",
    "data engineering": "Data Science",
    "software": "Software Engineering",
    "software engineer": "Software Engineering",
    "backend": "Software Engineering",
    "frontend": "Software Engineering",
    "fullstack": "Software Engineering",
}


def fetch(search: FreeApiSearch) -> list[JobListing]:
    params: dict[str, Any] = {"page": max(0, (search.page or 1) - 1)}
    # The Muse expects exact category labels; map common queries; otherwise omit.
    if search.query:
        normalized = search.query.casefold().strip()
        for key, label in _MUSE_CATEGORY_MAP.items():
            if key in normalized:
                params["category"] = label
                break
    if search.location:
        # Pass through known city names; The Muse uses "City, Country" style.
        params["location"] = search.location
    data = _fetch_json(search, "https://www.themuse.com/api/public/jobs", params=params)
    items = data.get("results", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _strip_html(item.get("contents") or "")
        company_info = item.get("company") or {}
        company = company_info.get("name") if isinstance(company_info, dict) else None
        locations = _string_list([loc.get("name") for loc in (item.get("locations") or []) if isinstance(loc, dict)])
        cats = _string_list([cat.get("name") for cat in (item.get("categories") or []) if isinstance(cat, dict)])
        tags = _string_list([tag.get("name") for tag in (item.get("tags") or []) if isinstance(tag, dict)])
        location = ", ".join(locations) or None
        url = (item.get("refs") or {}).get("landing_page") if isinstance(item.get("refs"), dict) else None
        remote = bool(locations) and any("remote" in (loc or "").lower() for loc in locations)
        jobs.append(_make_job(
            source="api:themuse",
            source_url=url,
            apply_url=url,
            raw_text=_join_nonempty(item.get("name"), company, location, desc, " ".join(cats + tags)),
            title=item.get("name") or "[To Be Parsed]",
            company=company or "[To Be Parsed]",
            location=location,
            remote=remote,
            work_mode="remote" if remote else None,
            job_type=item.get("type"),
            description=desc,
            tech_stack=cats + tags,
            posted_date=item.get("publication_date"),
        ))
    return _post_filter(jobs, search)
