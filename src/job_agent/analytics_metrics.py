"""Dashboard-ready metrics derived from local jobs, packets, and events."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import cast

from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus

_INTERVIEW = {
    JobStatus.INTERVIEW,
    JobStatus.INTERVIEWING,
    JobStatus.OFFERED,
    JobStatus.OFFER,
    JobStatus.ACCEPTED,
}
_RESPONSE = _INTERVIEW | {JobStatus.REPLIED, JobStatus.REJECTED}
_APPLIED = _RESPONSE | {
    JobStatus.APPLIED,
    JobStatus.SUBMITTED,
    JobStatus.MANUALLY_SUBMITTED,
    JobStatus.AUTO_SUBMITTED,
}
_PACKET = _APPLIED | {
    JobStatus.PACKET_READY,
    JobStatus.APPLYING,
    JobStatus.ASSISTED_APPLY_OPENED,
    JobStatus.APPLY_ATTEMPTED,
    JobStatus.NEEDS_MANUAL,
    JobStatus.OUTREACH_DRAFTED,
    JobStatus.OUTREACH_SENT,
    JobStatus.FOLLOWUP_DUE,
    JobStatus.FOLLOWUP_SENT,
}
_SCORED = _PACKET | {JobStatus.SCORED, JobStatus.NEEDS_REVIEW, JobStatus.QUALIFIED}
_BUCKETS = (("0-49", 0, 50), ("50-69", 50, 70), ("70-84", 70, 85), ("85-100", 85, 101))


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator * 100 / denominator, 1) if denominator else 0.0


def _source_name(job: JobListing) -> str:
    return (job.source or "unknown").removeprefix("api:") or "unknown"


def _application_date(db: Database, job: JobListing) -> date | None:
    dates: list[datetime] = []
    for event in db.get_events(job.id):
        event_type = str(event.get("event_type") or "")
        event_data = event.get("event_data") or {}
        new_status = str(event_data.get("new_status") or "") if isinstance(event_data, dict) else ""
        if event_type in {status.value for status in _APPLIED} or (
            event_type == "STATUS_CHANGED" and new_status in {status.value for status in _APPLIED}
        ):
            parsed = _parse_iso(str(event.get("created_at") or ""))
            if parsed:
                dates.append(parsed)
    if dates:
        return min(dates).date()
    fallback = _parse_iso(job.updated_at) if job.status in _APPLIED else None
    return fallback.date() if fallback else None


def _funnel(jobs: list[JobListing], packet_jobs: set[str]) -> list[dict[str, object]]:
    counts = {
        "added": len(jobs),
        "scored": sum(job.fit_score is not None or job.status in _SCORED for job in jobs),
        "packet": sum(job.id in packet_jobs or job.status in _PACKET for job in jobs),
        "applied": sum(job.status in _APPLIED for job in jobs),
        "response": sum(job.status in _RESPONSE for job in jobs),
        "interview": sum(job.status in _INTERVIEW for job in jobs),
    }
    labels = {
        "added": "Added",
        "scored": "Scored",
        "packet": "Packet ready",
        "applied": "Applied",
        "response": "Response",
        "interview": "Interview",
    }
    return [{"key": key, "label": labels[key], "count": count} for key, count in counts.items()]


def _sources(jobs: list[JobListing]) -> list[dict[str, object]]:
    tracked = Counter(_source_name(job) for job in jobs)
    applied = Counter(_source_name(job) for job in jobs if job.status in _APPLIED)
    return [
        {
            "source": source,
            "count": count,
            "applications": applied[source],
            "conversion_rate": _rate(applied[source], count),
        }
        for source, count in sorted(tracked.items(), key=lambda item: (-item[1], item[0].casefold()))
    ]


def _score_distribution(jobs: list[JobListing]) -> list[dict[str, object]]:
    scores = [float(job.fit_score) for job in jobs if job.fit_score is not None]
    return [
        {
            "label": label,
            "min": lower,
            "max": upper - 1,
            "count": sum(lower <= score < upper for score in scores),
        }
        for label, lower, upper in _BUCKETS
    ]


def _applications_over_time(
    db: Database,
    jobs: list[JobListing],
    today: date,
) -> list[dict[str, object]]:
    first = today - timedelta(days=59)
    counts = Counter(
        applied_on
        for job in jobs
        for applied_on in [_application_date(db, job)]
        if applied_on is not None and first <= applied_on <= today
    )
    return [
        {"date": (first + timedelta(days=offset)).isoformat(), "count": counts[first + timedelta(days=offset)]}
        for offset in range(60)
    ]


def compute_metrics(db: Database, *, now: datetime | None = None) -> dict[str, object]:
    """Return the stable JSON shape consumed by Overview and Insights."""
    generated = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    jobs = db.list_jobs(limit=None)
    packet_jobs = set(db.bulk_latest_packets([job.id for job in jobs]))
    funnel = _funnel(jobs, packet_jobs)
    counts = {str(row["key"]): cast(int, row["count"]) for row in funnel}
    statuses = Counter(job.status.value for job in jobs)
    return {
        "funnel": funnel,
        "sources": _sources(jobs),
        "score_distribution": _score_distribution(jobs),
        "applications_over_time": _applications_over_time(db, jobs, generated.date()),
        "status_now": [
            {"status": status, "count": count}
            for status, count in sorted(statuses.items(), key=lambda item: (-item[1], item[0]))
        ],
        "kpis": {
            "tracked": counts["added"],
            "scored": counts["scored"],
            "packets": counts["packet"],
            "applied": counts["applied"],
            "responses": counts["response"],
            "interviews": counts["interview"],
            "application_rate": _rate(counts["applied"], counts["added"]),
            "response_rate": _rate(counts["response"], counts["applied"]),
            "interview_rate": _rate(counts["interview"], counts["applied"]),
        },
        "generated_at": generated.isoformat(),
    }
