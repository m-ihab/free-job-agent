"""Shared internship classification helpers."""
from __future__ import annotations

from job_agent.schemas.job import JobListing

INTERNSHIP_KEYWORDS = (
    "intern",
    "internship",
    "stage",
    "stagiaire",
    "alternance",
    "apprentissage",
    "apprenti",
    "trainee",
)


def is_internship_listing(job: JobListing) -> bool:
    """Return True when the listing clearly looks like an internship."""
    parts = [
        job.title,
        job.company,
        job.location or "",
        job.job_type or "",
        job.seniority or "",
        job.description or "",
        job.raw_text or "",
        " ".join(job.tech_stack),
    ]
    text = "\n".join(parts).casefold()
    return any(keyword in text for keyword in INTERNSHIP_KEYWORDS)
