"""The needs-manual queue: DB round-trip + status vocabulary + dashboard payload."""
from __future__ import annotations

from job_agent.schemas.job import JobListing, JobStatus
from job_agent.ui.services import status_options


def test_needs_manual_status_is_exposed_to_ui():
    assert JobStatus.NEEDS_MANUAL.value in status_options()


def test_get_needs_manual_round_trip(tmp_db):
    job = JobListing(title="Data Scientist", company="ACME", source="paste", raw_text="x")
    tmp_db.save_job(job)
    # Not yet in the queue.
    assert tmp_db.get_needs_manual() == []
    tmp_db.update_job_status(job.id, JobStatus.NEEDS_MANUAL)
    queued = tmp_db.get_needs_manual()
    assert [j.id for j in queued] == [job.id]
    assert queued[0].status == JobStatus.NEEDS_MANUAL


def test_needs_manual_dashboard_payload_carries_wall_reason(monkeypatch, tmp_path):
    """The dashboard queue must show *why* a job was handed off — the wall reason
    logged by full-auto, surfaced as ``needs_manual_reason`` on each job."""
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.ui.server import _needs_manual_jobs, _tracker
    from job_agent.ui.services import configured_app

    config = configured_app()
    db = _tracker(config).db
    job = JobListing(title="Data Scientist", company="ACME", source="paste", raw_text="x")
    db.save_job(job)

    # Before hand-off the queue is empty.
    assert _needs_manual_jobs(config) == []

    db.update_job_status(job.id, JobStatus.NEEDS_MANUAL)
    db.log_event(job.id, "NEEDS_MANUAL", {"reason": "reCAPTCHA challenge", "note": "Full-auto hand-off"})

    payload = _needs_manual_jobs(config)
    assert [j["id"] for j in payload] == [job.id]
    assert payload[0]["needs_manual_reason"] == "reCAPTCHA challenge"
    assert payload[0]["needs_manual_reason_category"]["category"] == "CAPTCHA"


def test_needs_manual_payload_reason_blank_without_event(monkeypatch, tmp_path):
    """A NEEDS_MANUAL job with no logged reason still lists, with an empty reason
    (the UI falls back to a generic label)."""
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.ui.server import _needs_manual_jobs, _tracker
    from job_agent.ui.services import configured_app

    config = configured_app()
    db = _tracker(config).db
    job = JobListing(title="ML Engineer", company="Globex", source="paste", raw_text="x")
    db.save_job(job)
    db.update_job_status(job.id, JobStatus.NEEDS_MANUAL)

    payload = _needs_manual_jobs(config)
    assert [j["id"] for j in payload] == [job.id]
    assert payload[0]["needs_manual_reason"] == ""
    assert payload[0]["needs_manual_reason_category"]["category"] == "UNSPECIFIED"
