"""Row value helpers for the internship workbook exporter."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from job_agent.schemas.job import JobListing, JobStatus
from job_agent.tracker import ApplicationTracker

APPLIED_STATUSES = {JobStatus.APPLYING, JobStatus.APPLIED, JobStatus.MANUALLY_SUBMITTED, JobStatus.AUTO_SUBMITTED}
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")


def normalise_text(text: object) -> str:
    return str(text or "").strip().casefold()


def applied_at(tracker: ApplicationTracker, job: JobListing) -> str:
    expected_statuses = {normalise_text(status.value) for status in APPLIED_STATUSES}
    for event in tracker.get_history(job.id):
        event_type = normalise_text(event.get("event_type"))
        event_data = event.get("event_data") or {}
        new_status = normalise_text(event_data.get("new_status"))
        if event_type in ("manually_submitted", "auto_submitted", "chrome_session_queued") or new_status in expected_statuses:
            return str(event.get("created_at") or job.updated_at or job.created_at)[:10]
    return str(job.updated_at or job.created_at)[:10]


def contact_details(job: JobListing) -> str:
    parts: list[str] = []
    text = "\n".join([job.description or "", job.raw_text or ""])
    emails = list(dict.fromkeys(_EMAIL_RE.findall(text)))
    phones = list(dict.fromkeys(_PHONE_RE.findall(text)))
    if emails:
        parts.append("Emails: " + "; ".join(emails[:3]))
    if phones:
        parts.append("Phones: " + "; ".join(phones[:2]))
    if parts:
        return " | ".join(parts)
    for candidate in (job.apply_url, job.source_url):
        if not candidate:
            continue
        parsed = urlparse(candidate)
        if parsed.hostname:
            return f"Portal: {parsed.hostname}"
        return candidate
    return ""


def status_label(job: JobListing) -> str:
    if job.status in {JobStatus.APPLIED, JobStatus.MANUALLY_SUBMITTED, JobStatus.AUTO_SUBMITTED}:
        return "Applied"
    if job.status == JobStatus.APPLYING:
        return "Applying"
    return job.status.value.replace("_", " ").title()

