"""Local analytics over the application database.

The module computes funnel counts, weekly throughput, top companies, and a
basic CSV export. Everything stays local — there are no calls to external
services. All timestamps are interpreted as UTC ISO 8601 strings.
"""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus


# Statuses, in order, that make up the application funnel. Each later stage
# implies the earlier one — a job that reached APPLIED has also been SCORED.
FUNNEL_STAGES: list[tuple[str, list[JobStatus]]] = [
    ("Tracked", []),
    ("Scored", [JobStatus.SCORED, JobStatus.NEEDS_REVIEW, JobStatus.PACKET_READY, JobStatus.APPLYING, JobStatus.ASSISTED_APPLY_OPENED, JobStatus.APPLIED, JobStatus.MANUALLY_SUBMITTED, JobStatus.AUTO_SUBMITTED, JobStatus.REJECTED, JobStatus.INTERVIEW, JobStatus.OFFERED, JobStatus.ACCEPTED]),
    ("Packet ready", [JobStatus.PACKET_READY, JobStatus.APPLYING, JobStatus.ASSISTED_APPLY_OPENED, JobStatus.APPLIED, JobStatus.MANUALLY_SUBMITTED, JobStatus.AUTO_SUBMITTED, JobStatus.REJECTED, JobStatus.INTERVIEW, JobStatus.OFFERED, JobStatus.ACCEPTED]),
    ("Submitted", [JobStatus.APPLIED, JobStatus.MANUALLY_SUBMITTED, JobStatus.AUTO_SUBMITTED, JobStatus.REJECTED, JobStatus.INTERVIEW, JobStatus.OFFERED, JobStatus.ACCEPTED]),
    ("Interview+", [JobStatus.INTERVIEW, JobStatus.OFFERED, JobStatus.ACCEPTED]),
    ("Offer", [JobStatus.OFFERED, JobStatus.ACCEPTED]),
]


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _week_key(date: datetime) -> str:
    iso = date.astimezone(timezone.utc).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def compute_stats(db: Database, weeks: int = 8) -> dict:
    """Compute headline stats: funnel, weekly counts, top companies, scores."""
    jobs = db.list_jobs(limit=None)
    total = len(jobs)
    statuses = Counter(job.status.value for job in jobs)
    funnel = []
    for label, included in FUNNEL_STAGES:
        if not included:
            count = total
        else:
            # Each job has exactly one status, so summing the precomputed
            # per-status counts matches a full rescan without re-iterating jobs.
            count = sum(statuses[status.value] for status in included)
        funnel.append({"label": label, "count": count})

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(weeks=weeks)
    weekly_added: dict[str, int] = defaultdict(int)
    weekly_applied: dict[str, int] = defaultdict(int)
    submitted_statuses = {JobStatus.APPLIED.value, JobStatus.MANUALLY_SUBMITTED.value, JobStatus.AUTO_SUBMITTED.value, JobStatus.INTERVIEW.value, JobStatus.OFFERED.value, JobStatus.ACCEPTED.value, JobStatus.REJECTED.value}
    for job in jobs:
        created = _parse_iso(job.created_at)
        updated = _parse_iso(job.updated_at)
        if created and created >= cutoff:
            weekly_added[_week_key(created)] += 1
        if updated and updated >= cutoff and job.status.value in submitted_statuses:
            weekly_applied[_week_key(updated)] += 1

    week_keys = sorted(set(list(weekly_added) + list(weekly_applied)))
    if not week_keys:
        week_keys = [_week_key(now)]
    weekly = [
        {"week": key, "added": weekly_added.get(key, 0), "applied": weekly_applied.get(key, 0)}
        for key in week_keys
    ]

    top_companies = Counter(job.company.strip() for job in jobs if job.company.strip()).most_common(8)
    top_sources = Counter(job.source.replace("api:", "") for job in jobs if job.source).most_common(8)
    locations = Counter((job.location or "").strip() for job in jobs if (job.location or "").strip()).most_common(8)

    scored = [job.fit_score for job in jobs if isinstance(job.fit_score, (int, float))]
    avg_score = round(sum(scored) / len(scored), 1) if scored else None
    score_buckets = {"0-49": 0, "50-69": 0, "70-84": 0, "85-100": 0}
    for value in scored:
        if value < 50:
            score_buckets["0-49"] += 1
        elif value < 70:
            score_buckets["50-69"] += 1
        elif value < 85:
            score_buckets["70-84"] += 1
        else:
            score_buckets["85-100"] += 1

    submitted_count = sum(statuses.get(status, 0) for status in submitted_statuses)
    interview_count = sum(statuses.get(status, 0) for status in {JobStatus.INTERVIEW.value, JobStatus.OFFERED.value, JobStatus.ACCEPTED.value})
    response_rate = round(interview_count * 100 / submitted_count, 1) if submitted_count else 0.0

    return {
        "total": total,
        "statuses": dict(statuses),
        "funnel": funnel,
        "weekly": weekly,
        "top_companies": [{"name": name, "count": count} for name, count in top_companies],
        "top_sources": [{"name": name, "count": count} for name, count in top_sources],
        "top_locations": [{"name": name, "count": count} for name, count in locations],
        "avg_score": avg_score,
        "score_buckets": score_buckets,
        "submitted_count": submitted_count,
        "interview_count": interview_count,
        "response_rate": response_rate,
        "generated_at": now.isoformat(),
    }


def jobs_to_csv(jobs: Iterable[JobListing]) -> str:
    """Render tracked jobs as CSV text suitable for spreadsheets."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "id",
        "title",
        "company",
        "location",
        "remote",
        "work_mode",
        "job_type",
        "status",
        "fit_score",
        "fit_decision",
        "source",
        "apply_url",
        "tech_stack",
        "posted_date",
        "created_at",
        "updated_at",
    ])
    for job in jobs:
        writer.writerow([
            job.id,
            job.title,
            job.company,
            job.location or "",
            "yes" if job.remote else "no",
            job.work_mode or "",
            job.job_type or "",
            job.status.value,
            job.fit_score if job.fit_score is not None else "",
            job.fit_decision or "",
            job.source,
            job.apply_url or job.source_url or "",
            "; ".join(job.tech_stack),
            job.posted_date or "",
            job.created_at,
            job.updated_at,
        ])
    return buffer.getvalue()


def export_jobs_csv(db: Database, output_path: Path) -> Path:
    """Write a CSV of all tracked jobs to the given path."""
    jobs = db.list_jobs(limit=None)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(jobs_to_csv(jobs), encoding="utf-8")
    return output_path
