"""Ingest job description from a local text or markdown file."""
from __future__ import annotations

from pathlib import Path

from job_agent.schemas.job import JobListing


def ingest_file(path: Path | str, title: str | None = None, company: str | None = None, url: str | None = None) -> JobListing:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return JobListing(
        source="file",
        source_url=url,
        apply_url=url,
        raw_text=text.strip(),
        title=title or "[To Be Parsed]",
        company=company or "[To Be Parsed]",
    )
