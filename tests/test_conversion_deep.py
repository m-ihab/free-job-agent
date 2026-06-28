"""Deeper Conversion OS behaviours: follow-ups, learning, manual reasons."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_agent.config import AppConfig
from job_agent.conversion import build_today_queue
from job_agent.conversion_followups import list_due_followups, sync_followup_tasks
from job_agent.conversion_learning import learning_summary
from job_agent.manual_reasons import categorize_manual_reason
from job_agent.schemas.job import JobListing, JobStatus


NOW = datetime(2026, 6, 27, tzinfo=timezone.utc)


def _iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _job(
    status: JobStatus,
    *,
    source: str = "manual",
    score: float | None = 70,
    updated_days_ago: int = 0,
    tech_stack: list[str] | None = None,
) -> JobListing:
    return JobListing(
        title="Data Scientist",
        company="ACME",
        location="Paris",
        source=source,
        status=status,
        fit_score=score,
        tech_stack=tech_stack or [],
        created_at=_iso(updated_days_ago),
        updated_at=_iso(updated_days_ago),
    )


def test_followup_task_round_trip(tmp_db):
    job = _job(JobStatus.MANUALLY_SUBMITTED)
    tmp_db.save_job(job)
    due_at = "2026-06-20T00:00:00+00:00"

    task_id = tmp_db.upsert_followup_task(job.id, "week1", due_at)

    tasks = tmp_db.list_followup_tasks(status="due", due_before="2026-06-27T00:00:00+00:00")
    assert tasks == [{
        "id": task_id,
        "job_id": job.id,
        "kind": "week1",
        "due_at": due_at,
        "status": "due",
        "created_at": tasks[0]["created_at"],
        "updated_at": tasks[0]["updated_at"],
    }]

    assert tmp_db.complete_followup_task(task_id) is True
    assert tmp_db.list_followup_tasks(status="due") == []


def test_sync_followup_tasks_creates_due_week1_and_week2(tmp_db):
    job = _job(JobStatus.MANUALLY_SUBMITTED, updated_days_ago=15)
    tmp_db.save_job(job)
    job.updated_at = _iso(15)

    created = sync_followup_tasks(tmp_db, [job])
    due = list_due_followups(tmp_db, [job], now=NOW)

    assert created == 2
    assert [item.kind for item in due] == ["week1", "week2"]
    assert due[0].days_overdue == 8


def test_learning_summary_groups_sources_and_skills():
    jobs = [
        _job(JobStatus.MANUALLY_SUBMITTED, source="France Travail", tech_stack=["Python", "SQL"], score=80),
        _job(JobStatus.INTERVIEW, source="France Travail", tech_stack=["Python"], score=90),
        _job(JobStatus.REJECTED, source="Manual", tech_stack=["Excel"], score=40),
    ]

    summary = learning_summary(jobs)

    assert summary["sources"][0]["label"] == "France Travail"
    assert summary["sources"][0]["submitted"] == 2
    assert summary["skills"][0]["label"] == "Python"


def test_today_queue_gets_small_learning_boost(tmp_path):
    config = AppConfig(data_dir=tmp_path)
    proven = _job(JobStatus.INTERVIEW, source="France Travail", tech_stack=["Python"], score=80)
    new_from_good_source = _job(JobStatus.PACKET_READY, source="France Travail", tech_stack=["Python"], score=70)
    new_other = _job(JobStatus.PACKET_READY, source="Manual", tech_stack=["Excel"], score=70)

    queue = build_today_queue([new_other, proven, new_from_good_source], config, now=NOW)

    assert queue[0].job_id == proven.id
    assert queue[1].job_id == new_from_good_source.id


def test_manual_reason_taxonomy_recognizes_common_walls():
    assert categorize_manual_reason("reCAPTCHA challenge")["category"] == "CAPTCHA"
    assert categorize_manual_reason("unknown required field: visa")["category"] == "UNKNOWN_FIELD"
    assert categorize_manual_reason("")["category"] == "UNSPECIFIED"
