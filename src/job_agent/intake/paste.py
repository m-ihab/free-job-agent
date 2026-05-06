"""Ingest job description from pasted text."""
from job_agent.schemas.job import JobListing


def ingest_paste(text: str) -> JobListing:
    """Create a JobListing from pasted raw text. Title/company will need normalization."""
    return JobListing(
        source="paste",
        raw_text=text.strip(),
        title="[To Be Parsed]",
        company="[To Be Parsed]",
    )
