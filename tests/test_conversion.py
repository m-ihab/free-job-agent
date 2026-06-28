"""Pipeline / conversion cockpit core behaviour."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_agent.config import AppConfig
from job_agent.conversion import (
    build_today_queue,
    conversion_metrics,
    detect_stale,
    get_job_notes,
    next_best_action,
    pipeline_stage,
    set_job_notes,
)
from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus


def _iso(days_ago: int) -> str:
    return (datetime(2026, 6, 27, tzinfo=timezone.utc) - timedelta(days=days_ago)).isoformat()


def _job(status: JobStatus, *, score: float | None = 70, updated_days_ago: int = 0) -> JobListing:
    return JobListing(
        title=f"{status.value} job",
        company="ACME",
        location="Paris",
        status=status,
        fit_score=score,
        created_at=_iso(updated_days_ago),
        updated_at=_iso(updated_days_ago),
    )


def test_pipeline_stage_forward_maps_existing_statuses():
    assert pipeline_stage(_job(JobStatus.NEW)) == "DISCOVERED"
    assert pipeline_stage(_job(JobStatus.SCORED)) == "QUALIFIED"
    assert pipeline_stage(_job(JobStatus.PACKET_READY)) == "PACKET_READY"
    assert pipeline_stage(_job(JobStatus.MANUALLY_SUBMITTED)) == "SUBMITTED"
    assert pipeline_stage(_job(JobStatus.INTERVIEW)) == "INTERVIEWING"
    assert pipeline_stage(_job(JobStatus.OFFERED)) == "OFFER"


def test_next_best_action_for_common_statuses(tmp_path):
    config = AppConfig(data_dir=tmp_path, stale_days=14)
    now = datetime(2026, 6, 27, tzinfo=timezone.utc)

    assert next_best_action(_job(JobStatus.NEW), config, now).action == "Run preflight"
    assert next_best_action(_job(JobStatus.PACKET_READY), config, now).action == "Apply"
    assert next_best_action(_job(JobStatus.NEEDS_MANUAL), config, now).action == "Finish manual apply"
    assert next_best_action(_job(JobStatus.MANUALLY_SUBMITTED, updated_days_ago=8), config, now).action == "Send follow-up"
    assert next_best_action(_job(JobStatus.INTERVIEW), config, now).action == "Prepare interview"


def test_today_queue_orders_manual_then_due_then_high_score(tmp_path):
    config = AppConfig(data_dir=tmp_path, stale_days=14)
    now = datetime(2026, 6, 27, tzinfo=timezone.utc)
    jobs = [
        _job(JobStatus.PACKET_READY, score=95),
        _job(JobStatus.NEEDS_MANUAL, score=50),
        _job(JobStatus.MANUALLY_SUBMITTED, score=80, updated_days_ago=8),
    ]

    queue = build_today_queue(jobs, config, now=now)

    assert [item.action for item in queue[:3]] == ["Finish manual apply", "Send follow-up", "Apply"]


def test_detect_stale_ignores_terminal_jobs(tmp_path):
    config = AppConfig(data_dir=tmp_path, stale_days=14)
    now = datetime(2026, 6, 27, tzinfo=timezone.utc)
    jobs = [
        _job(JobStatus.PACKET_READY, updated_days_ago=15),
        _job(JobStatus.REJECTED, updated_days_ago=40),
    ]

    stale = detect_stale(jobs, config, now=now)

    assert [item.job_id for item in stale] == [jobs[0].id]
    assert stale[0].days_idle == 15


def test_conversion_metrics_counts_funnel():
    jobs = [
        _job(JobStatus.NEW),
        _job(JobStatus.PACKET_READY),
        _job(JobStatus.MANUALLY_SUBMITTED),
        _job(JobStatus.INTERVIEW),
        _job(JobStatus.OFFERED),
    ]

    metrics = conversion_metrics(jobs)

    assert metrics.total == 5
    assert metrics.submitted == 3
    assert metrics.interview_rate == 0.67
    assert metrics.offer_rate == 0.33


def test_job_notes_round_trip(tmp_path):
    config = AppConfig(data_dir=tmp_path, db_path=tmp_path / "jobs.db")
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = _job(JobStatus.NEW)
    db.save_job(job)

    set_job_notes(config, job.id, "Follow up with alumni contact.")

    assert get_job_notes(config, job.id) == "Follow up with alumni contact."
