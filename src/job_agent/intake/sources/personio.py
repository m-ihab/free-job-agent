"""Personio public XML jobs feed connector."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from job_agent.intake.url import HEADERS
from job_agent.schemas.job import JobListing

from . import base
from .base import (
    FreeApiError,
    FreeApiSearch,
    _bounded_limit,
    _join_nonempty,
    _make_job,
    _post_filter,
    _strip_html,
)


def fetch(search: FreeApiSearch) -> list[JobListing]:
    if not search.board:
        raise FreeApiError(
            "personio requires --board with the company subdomain. Example: personio --board examplecompany"
        )
    url = f"https://{search.board}.jobs.personio.com/xml"
    clean_params = {}  # noqa: F841
    headers = {**HEADERS, "Accept": "application/xml,text/xml,*/*"}
    response = base.requests.get(url, headers=headers, timeout=search.timeout)
    response.raise_for_status()
    xml_text = response.text
    # Lightweight XML parsing (Personio feeds are small).
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FreeApiError(f"Personio XML parse error for {search.board}: {exc}")
    positions = list(root.iter("position"))
    jobs: list[JobListing] = []
    for position in positions[: _bounded_limit(search.limit)]:
        def _field(tag: str) -> str:
            el = position.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""
        title = _field("name") or "[To Be Parsed]"
        location = _field("office") or _field("city")
        department = _field("department")
        recruiting_category = _field("recruitingCategory")
        employment_type = _field("employmentType")
        desc_parts: list[str] = []
        for jd in position.iter("jobDescriptions"):
            for d in jd.iter("jobDescription"):
                name = d.find("name")
                value = d.find("value")
                if name is not None and value is not None and value.text:
                    desc_parts.append((name.text or "").strip() + ": " + _strip_html(value.text))
        desc = "\n\n".join(desc_parts)
        post_id = _field("id")
        public_url = f"https://{search.board}.jobs.personio.com/job/{post_id}" if post_id else None
        jobs.append(_make_job(
            source="api:personio",
            source_url=public_url,
            apply_url=public_url,
            raw_text=_join_nonempty(title, search.board, location, desc, department, recruiting_category),
            title=title,
            company=search.board,
            location=location or None,
            remote="remote" in (location.lower() + " " + (desc or "").lower()),
            job_type=employment_type or None,
            description=desc,
            tech_stack=[t for t in [department, recruiting_category] if t],
            posted_date=_field("createdAt"),
        ))
    return _post_filter(jobs, search)
