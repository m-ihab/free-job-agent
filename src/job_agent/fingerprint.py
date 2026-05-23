"""Generate deterministic fingerprints for job deduplication."""
from __future__ import annotations

import hashlib
import re

from job_agent.schemas.job import JobListing


# Markers that vary across the same job (gender markers, plural variants).
_NORMALIZE_NOISE = re.compile(
    r"\b(h/f|f/h|h-f|f-h|m/f|f/m|h/f/x|m/w/d|w/m/d|x/h/f|\(h/f\)|\(f/h\)|\(h/f/x\)|\.e|·e)\b",
    re.IGNORECASE,
)
_LOCATION_VARIANTS = re.compile(
    r"\b(paris\s+\d{1,2}(er|ème|e)?\s+arrondissement?|paris\s+\d{1,2}(er|ème|e)?|\d{1,2}(er|ème|e)?\s+arrondissement?|75\d{3})\b",
    re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
    """Lowercase, strip H/F markers, drop arrondissement, collapse whitespace."""
    text = text.lower()
    text = _NORMALIZE_NOISE.sub(" ", text)
    text = _LOCATION_VARIANTS.sub("paris", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _short_signature(title: str, company: str, location: str) -> str:
    """A compact signature on (title, company, normalized location)."""
    parts = [_normalize_text(title), _normalize_text(company), _normalize_text(location)]
    return " | ".join(parts)


def compute_fingerprint(job: JobListing) -> str:
    """Stable SHA-256 fingerprint that ignores cosmetic title/location variants.

    Two listings for the same role that differ only in ``(H/F)`` vs
    ``(F/H)``, ``Paris`` vs ``Paris 1er Arrondissement``, or slight
    description rewording, now produce the same fingerprint.
    """
    canonical = _short_signature(job.title, job.company, job.location or "")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def set_fingerprint(job: JobListing) -> JobListing:
    """Compute and set the fingerprint on a job listing."""
    job.fingerprint = compute_fingerprint(job)
    return job
