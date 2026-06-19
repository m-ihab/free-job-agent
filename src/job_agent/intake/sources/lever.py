"""Lever public Postings API connector."""
from __future__ import annotations

from typing import Any

from job_agent.schemas.job import JobListing

from .base import (
    FreeApiError,
    FreeApiSearch,
    _bounded_limit,
    _fetch_json,
    _join_nonempty,
    _make_job,
    _post_filter,
    _string_list,
    _strip_html,
)


def _lever_location(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return ""


def fetch(search: FreeApiSearch) -> list[JobListing]:
    if not search.board:
        raise FreeApiError("lever requires --board with the Lever site slug, for example: lever --board leverdemo")
    data = _fetch_json(
        search,
        f"https://api.lever.co/v0/postings/{search.board}",
        params={"mode": "json", "limit": _bounded_limit(search.limit)},
    )
    items = data if isinstance(data, list) else []
    jobs: list[JobListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        lists = item.get("lists") or []
        list_text = []
        if isinstance(lists, list):
            for block in lists:
                if isinstance(block, dict):
                    list_text.append(_join_nonempty(block.get("text"), block.get("content")))
        desc = _strip_html(_join_nonempty(item.get("description"), item.get("descriptionPlain"), item.get("additionalPlain"), "\n".join(list_text)))
        categories = item.get("categories") or {}
        team = categories.get("team") if isinstance(categories, dict) else None
        commitment = categories.get("commitment") if isinstance(categories, dict) else None
        location = _lever_location(categories.get("location") if isinstance(categories, dict) else None)
        jobs.append(_make_job(
            source="api:lever",
            source_url=item.get("hostedUrl") or item.get("applyUrl"),
            apply_url=item.get("hostedUrl") or item.get("applyUrl"),
            raw_text=_join_nonempty(item.get("text"), search.board, location, commitment, desc),
            title=item.get("text") or "[To Be Parsed]",
            company=search.board,
            location=location or None,
            remote="remote" in (location.lower() + " " + desc.lower()),
            work_mode="remote" if "remote" in (location.lower() + " " + desc.lower()) else None,
            job_type=commitment,
            description=desc,
            tech_stack=_string_list(team),
            posted_date=str(item.get("createdAt")) if item.get("createdAt") else None,
        ))
    return _post_filter(jobs, search)
