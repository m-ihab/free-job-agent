"""Timing intelligence for the conversion cockpit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_agent.config import AppConfig
from job_agent.conversion import build_today_queue, next_best_action
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.timing import job_timing_signal


NOW = datetime(2026, 6, 27, tzinfo=timezone.utc)


def _iso(hours_ago: int) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _job(*, status: JobStatus = JobStatus.PACKET_READY, posted_hours_ago: int | None = None, score: float = 80) -> JobListing:
    return JobListing(
        title="Data Scientist Intern",
        company="ACME",
        location="Paris",
        status=status,
        fit_score=score,
        posted_date=_iso(posted_hours_ago) if posted_hours_ago is not None else None,
        created_at=_iso(120),
        updated_at=_iso(120),
    )


def test_job_timing_signal_prefers_posted_date_over_created_at(tmp_path):
    config = AppConfig(data_dir=tmp_path, freshness_recent_hours=72)
    signal = job_timing_signal(_job(posted_hours_ago=12), config, now=NOW)

    assert signal.bucket == "fresh"
    assert signal.priority_boost == 90
    assert signal.age_hours == 12
    assert "posted 12h ago" in signal.reason


def test_job_timing_signal_marks_old_jobs_as_aging(tmp_path):
    config = AppConfig(data_dir=tmp_path, freshness_recent_hours=48)
    signal = job_timing_signal(_job(posted_hours_ago=96), config, now=NOW)

    assert signal.bucket == "aging"
    assert signal.priority_boost == 0
    assert signal.age_hours == 96


def test_next_best_action_includes_freshness_reason(tmp_path):
    config = AppConfig(data_dir=tmp_path, freshness_recent_hours=72)

    action = next_best_action(_job(posted_hours_ago=6), config, NOW)

    assert action.action == "Apply"
    assert action.priority > 850
    assert "Fresh posting" in action.reason


def test_today_queue_prioritizes_fresh_high_fit_jobs(tmp_path):
    config = AppConfig(data_dir=tmp_path, freshness_recent_hours=72)
    old = _job(posted_hours_ago=180, score=95)
    fresh = _job(posted_hours_ago=4, score=85)

    queue = build_today_queue([old, fresh], config, now=NOW)

    assert queue[0].job_id == fresh.id
