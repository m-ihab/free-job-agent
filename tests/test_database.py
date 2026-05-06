"""Tests for the database layer."""
import pytest

from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, PacketStatus


def test_initialize_creates_tables(tmp_db):
    """Tables should exist after initialize."""
    import sqlite3
    conn = sqlite3.connect(tmp_db.db_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "jobs" in tables
    assert "packets" in tables
    assert "events" in tables


def test_save_and_get_job(tmp_db, sample_job):
    tmp_db.save_job(sample_job)
    fetched = tmp_db.get_job(sample_job.id)
    assert fetched is not None
    assert fetched.id == sample_job.id
    assert fetched.title == sample_job.title
    assert fetched.company == sample_job.company
    assert fetched.remote is True
    assert fetched.tech_stack == sample_job.tech_stack


def test_get_job_by_fingerprint(tmp_db, sample_job):
    sample_job.fingerprint = "abc123"
    tmp_db.save_job(sample_job)
    fetched = tmp_db.get_job_by_fingerprint("abc123")
    assert fetched is not None
    assert fetched.id == sample_job.id


def test_get_job_by_fingerprint_missing(tmp_db):
    result = tmp_db.get_job_by_fingerprint("nonexistent")
    assert result is None


def test_list_jobs_all(tmp_db):
    job1 = JobListing(title="Job A", company="Corp A")
    job2 = JobListing(title="Job B", company="Corp B")
    tmp_db.save_job(job1)
    tmp_db.save_job(job2)
    jobs = tmp_db.list_jobs()
    assert len(jobs) == 2


def test_list_jobs_with_status_filter(tmp_db):
    job1 = JobListing(title="Job A", company="Corp A", status=JobStatus.NEW)
    job2 = JobListing(title="Job B", company="Corp B", status=JobStatus.APPLIED)
    tmp_db.save_job(job1)
    tmp_db.save_job(job2)

    new_jobs = tmp_db.list_jobs(status=JobStatus.NEW)
    applied_jobs = tmp_db.list_jobs(status=JobStatus.APPLIED)
    assert len(new_jobs) == 1
    assert new_jobs[0].title == "Job A"
    assert len(applied_jobs) == 1
    assert applied_jobs[0].title == "Job B"


def test_update_job_status(tmp_db, sample_job):
    tmp_db.save_job(sample_job)
    tmp_db.update_job_status(sample_job.id, JobStatus.APPLIED)
    fetched = tmp_db.get_job(sample_job.id)
    assert fetched.status == JobStatus.APPLIED


def test_delete_job(tmp_db, sample_job):
    tmp_db.save_job(sample_job)
    tmp_db.delete_job(sample_job.id)
    assert tmp_db.get_job(sample_job.id) is None


def test_save_and_get_packet(tmp_db, sample_job):
    tmp_db.save_job(sample_job)
    packet = ApplicationPacket(job_id=sample_job.id, tailored_cv_md="# CV\n\nContent")
    tmp_db.save_packet(packet)
    fetched = tmp_db.get_packet(packet.id)
    assert fetched is not None
    assert fetched.job_id == sample_job.id
    assert fetched.tailored_cv_md == "# CV\n\nContent"


def test_get_packets_for_job(tmp_db, sample_job):
    tmp_db.save_job(sample_job)
    p1 = ApplicationPacket(job_id=sample_job.id, version=1)
    p2 = ApplicationPacket(job_id=sample_job.id, version=2)
    tmp_db.save_packet(p1)
    tmp_db.save_packet(p2)
    packets = tmp_db.get_packets_for_job(sample_job.id)
    assert len(packets) == 2
    # Should be sorted descending by version
    assert packets[0].version >= packets[1].version


def test_log_event_and_get_events(tmp_db, sample_job):
    tmp_db.save_job(sample_job)
    tmp_db.log_event(sample_job.id, "TEST_EVENT", {"key": "value"})
    events = tmp_db.get_events(sample_job.id)
    assert len(events) == 1
    assert events[0]["event_type"] == "TEST_EVENT"
    assert events[0]["event_data"]["key"] == "value"
