"""Generate deterministic fingerprints for job deduplication."""
from __future__ import annotations

import hashlib
import re

from job_agent.schemas.job import JobListing


def _normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def compute_fingerprint(job: JobListing) -> str:
    """Create a stable SHA-256 fingerprint based on title + company + location."""
    parts = [
        _normalize_text(job.title),
        _normalize_text(job.company),
        _normalize_text(job.location or ""),
    ]
    desc_snippet = _normalize_text(job.description[:500] if job.description else "")
    parts.append(desc_snippet)
    canonical = " | ".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def set_fingerprint(job: JobListing) -> JobListing:
    """Compute and set the fingerprint on a job listing."""
    job.fingerprint = compute_fingerprint(job)
    return job
