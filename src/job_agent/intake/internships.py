"""Shared internship/alternance classification helpers."""
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

_STAGE_KEYWORDS = ("intern", "internship", "stage", "stagiaire", "trainee")
_ALTERNANCE_KEYWORDS = ("alternance", "apprentissage", "apprenti", "apprentice", "alternant")


def _strong_text(job: JobListing) -> str:
    return f"{job.title} {job.job_type or ''} {job.seniority or ''}".casefold()


def _weak_text(job: JobListing) -> str:
    return (job.description or "").casefold()


def is_internship_listing(job: JobListing) -> bool:
    """Return True when the listing is an internship or alternance of any kind."""
    strong = _strong_text(job)
    weak = _weak_text(job)
    for keyword in INTERNSHIP_KEYWORDS:
        pattern = r"\b" + re.escape(keyword) + r"s?\b"
        if re.search(pattern, strong):
            return True
    body_hits = sum(1 for kw in INTERNSHIP_KEYWORDS if re.search(r"\b" + re.escape(kw) + r"s?\b", weak))
    return body_hits >= 2


def is_stage_listing(job: JobListing) -> bool:
    """Return True when the listing is specifically a stage/internship (not alternance)."""
    strong = _strong_text(job)
    for kw in _STAGE_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"s?\b", strong):
            return True
    return False


def is_alternance_listing(job: JobListing) -> bool:
    """Return True when the listing is specifically an alternance/apprentissage contract."""
    strong = _strong_text(job)
    weak = _weak_text(job)
    for kw in _ALTERNANCE_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"s?\b", strong):
            return True
    hits = sum(1 for kw in _ALTERNANCE_KEYWORDS if re.search(r"\b" + re.escape(kw) + r"s?\b", weak))
    return hits >= 2
