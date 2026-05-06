"""Tests for the ApplicationTracker."""
import pytest

from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket
from job_agent.tracker import ApplicationTracker


@pytest.fixture
def tracker(tmp_db):
    return ApplicationTracker(tmp_db)


def test_add_job_saves_and_logs(tracker, sample_job):
    tracker.add_job(sample_job)
    fetched = tracker.get_job(sample_job.id)
    assert fetched is not None
    assert fetched.title == sample_job.title

    events = tracker.get_history(sample_job.id)
    assert len(events) == 1
    assert events[0]["event_type"] == "JOB_ADDED"


def test_update_status_changes_status_and_logs(tracker, sample_job):
    tracker.add_job(sample_job)
    tracker.update_status(sample_job.id, JobStatus.APPLIED, note="Applied via website")

    fetched = tracker.get_job(sample_job.id)
    assert fetched.status == JobStatus.APPLIED

    events = tracker.get_history(sample_job.id)
    status_events = [e for e in events if e["event_type"] == "STATUS_CHANGED"]
    assert len(status_events) == 1
    assert status_events[0]["event_data"]["new_status"] == "APPLIED"
    assert status_events[0]["event_data"]["note"] == "Applied via website"


def test_save_packet_saves_and_logs(tracker, sample_job):
    tracker.add_job(sample_job)
    packet = ApplicationPacket(job_id=sample_job.id, tailored_cv_md="# CV")
    tracker.save_packet(packet)

    fetched = tracker.db.get_packet(packet.id)
    assert fetched is not None
    assert fetched.tailored_cv_md == "# CV"

    events = tracker.get_history(sample_job.id)
    packet_events = [e for e in events if e["event_type"] == "PACKET_SAVED"]
    assert len(packet_events) == 1
    assert packet_events[0]["event_data"]["packet_id"] == packet.id


def test_list_jobs_returns_all(tracker):
    j1 = JobListing(title="Job A", company="Corp A")
    j2 = JobListing(title="Job B", company="Corp B")
    tracker.add_job(j1)
    tracker.add_job(j2)
    jobs = tracker.list_jobs()
    assert len(jobs) == 2


def test_list_jobs_with_status_filter(tracker):
    j1 = JobListing(title="Job A", company="Corp A", status=JobStatus.NEW)
    j2 = JobListing(title="Job B", company="Corp B", status=JobStatus.APPLIED)
    tracker.add_job(j1)
    tracker.add_job(j2)

    new_jobs = tracker.list_jobs(status=JobStatus.NEW)
    assert len(new_jobs) == 1
    assert new_jobs[0].title == "Job A"


def test_get_history_returns_events(tracker, sample_job):
    tracker.add_job(sample_job)
    tracker.update_status(sample_job.id, JobStatus.SCORED)
    tracker.update_status(sample_job.id, JobStatus.APPLIED)

    events = tracker.get_history(sample_job.id)
    assert len(events) == 3  # JOB_ADDED + 2 STATUS_CHANGED
