"""Shared internship classification helpers."""
from __future__ import annotations

import re

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
    strong_parts = [
        job.title,
        job.job_type or "",
        job.seniority or "",
    ]
    weak_parts = [
        job.description or "",
        " ".join(job.tech_stack),
    ]
    strong_text = "\n".join(str(part or "") for part in strong_parts).casefold()
    weak_text = "\n".join(str(part or "") for part in weak_parts).casefold()

    # Company names such as "Stage Entertainment" must not make a normal job
    # look like an internship. Title/contract fields are authoritative; body
    # text is only a secondary signal and still uses whole-word matching.
    for keyword in INTERNSHIP_KEYWORDS:
        pattern = r"\b" + re.escape(keyword) + r"s?\b"
        if re.search(pattern, strong_text):
            return True
    body_hits = sum(1 for keyword in INTERNSHIP_KEYWORDS if re.search(r"\b" + re.escape(keyword) + r"s?\b", weak_text))
    return body_hits >= 2
