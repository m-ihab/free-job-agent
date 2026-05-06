"""Ingest job description from a local text or markdown file."""
from __future__ import annotations

from pathlib import Path

from job_agent.schemas.job import JobListing


def ingest_file(path: Path | str) -> JobListing:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return JobListing(
        source="file",
        raw_text=text.strip(),
        title="[To Be Parsed]",
        company="[To Be Parsed]",
    )
