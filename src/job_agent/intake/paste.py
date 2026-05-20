"""Ingest job description from pasted text."""
from __future__ import annotations

from job_agent.schemas.job import JobListing


def ingest_paste(text: str, title: str | None = None, company: str | None = None, url: str | None = None) -> JobListing:
    return JobListing(
        source="paste",
        raw_text=text.strip(),
        title=title or "[To Be Parsed]",
        company=company or "[To Be Parsed]",
        source_url=url,
        apply_url=url,
    )
