"""Ashby public Job Postings API connector."""
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
        raise FreeApiError("ashby requires --board with the Ashby job board name, for example: ashby --board Ashby")
    data = _fetch_json(
        search,
        f"https://api.ashbyhq.com/posting-api/job-board/{search.board}",
        params={"includeCompensation": "true"},
    )
    items = data.get("jobs", []) if isinstance(data, dict) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _strip_html(item.get("descriptionPlain") or item.get("descriptionHtml"))
        location = item.get("location") or ""
        comp = item.get("compensation") or {}
        salary_min = salary_max = None
        salary_currency = "USD"
        if isinstance(comp, dict):
            for component in comp.get("summaryComponents", []) or []:
                if not isinstance(component, dict):
                    continue
                if component.get("compensationType") == "Salary":
                    salary_min = component.get("minValue")
                    salary_max = component.get("maxValue")
                    salary_currency = component.get("currencyCode") or salary_currency
                    break
        jobs.append(_make_job(
            source="api:ashby",
            source_url=item.get("jobUrl"),
            apply_url=item.get("applyUrl") or item.get("jobUrl"),
            raw_text=_join_nonempty(item.get("title"), search.board, location, item.get("department"), item.get("team"), desc),
            title=item.get("title") or "[To Be Parsed]",
            company=search.board,
            location=location or None,
            remote=bool(item.get("isRemote")) or str(item.get("workplaceType", "")).lower() == "remote",
            work_mode=str(item.get("workplaceType") or "").lower() or None,
            job_type=item.get("employmentType"),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            description=desc,
            tech_stack=_string_list([item.get("department"), item.get("team")]),
            posted_date=item.get("publishedAt"),
        ))
    return _post_filter(jobs, search)
