"""Follow-up scheduling helpers for the Pipeline cockpit."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus

FOLLOWUP_OFFSETS = {"week1": 7, "week2": 14}
_SUBMITTED = {JobStatus.APPLIED, JobStatus.SUBMITTED, JobStatus.MANUALLY_SUBMITTED, JobStatus.AUTO_SUBMITTED}


@dataclass(frozen=True)
class DueFollowup:
    task_id: int
    job_id: str
    title: str
    company: str
    kind: str
    due_at: str
    days_overdue: int
    fit_score: float | None

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def sync_followup_tasks(db: Database, jobs: list[JobListing]) -> int:
    created = 0
    for job in jobs:
        if job.status not in _SUBMITTED:
            continue
        base = _parse_time(job.updated_at or job.created_at)
        existing = {
            (row["job_id"], row["kind"], row["due_at"])
            for row in db.list_followup_tasks(limit=500)
            if row["job_id"] == job.id
        }
        for kind, days in FOLLOWUP_OFFSETS.items():
            due_at = (base + timedelta(days=days)).isoformat()
            before = (job.id, kind, due_at) in existing
            db.upsert_followup_task(job.id, kind, due_at)
            if not before:
                created += 1
    return created


def list_due_followups(
    db: Database,
    jobs: list[JobListing],
    *,
    now: datetime | None = None,
    limit: int = 20,
) -> list[DueFollowup]:
    now = now or datetime.now(timezone.utc)
    jobs_by_id = {job.id: job for job in jobs}
    rows = db.list_followup_tasks(status="due", due_before=now.isoformat(), limit=limit)
    due: list[DueFollowup] = []
    for row in rows:
        job = jobs_by_id.get(str(row["job_id"]))
        if job is None:
            continue
        due_at = _parse_time(str(row["due_at"]))
        due.append(
            DueFollowup(
                task_id=int(row["id"]),
                job_id=job.id,
                title=job.title,
                company=job.company,
                kind=str(row["kind"]),
                due_at=str(row["due_at"]),
                days_overdue=max(0, int((now - due_at).total_seconds() // 86400)),
                fit_score=job.fit_score,
            )
        )
    return due


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
