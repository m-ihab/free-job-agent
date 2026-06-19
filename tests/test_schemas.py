"""Tests for Pydantic schemas."""
import json
from pathlib import Path


from job_agent.schemas.candidate import CandidateProfile, MasterCV, QAProfile
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, PacketStatus

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_candidate_profile_from_example():
    with open(EXAMPLES_DIR / "candidate_profile.json") as f:
        data = json.load(f)
    profile = CandidateProfile(**data)
    assert profile.contact.name == "Candidate Data AI Paris"
    assert profile.contact.email == "candidate@example.com"
    assert profile.remote_ok is True
    assert len(profile.skills) == 10
    assert any(s.name == "Python" for s in profile.skills)


def test_master_cv_from_example():
    with open(EXAMPLES_DIR / "master_cv.json") as f:
        data = json.load(f)
    cv = MasterCV(**data)
    assert cv.contact.name == "Candidate Data AI Paris"
    assert len(cv.experience) == 1
    assert len(cv.education) == 1
    assert len(cv.projects) == 2
    assert len(cv.certifications) == 0
    assert len(cv.skills) > 0


def test_qa_profile_from_example():
    with open(EXAMPLES_DIR / "master_qa_profile.json") as f:
        data = json.load(f)
    qa = QAProfile(**data)
    assert len(qa.entries) == 5
    assert all(e.locked for e in qa.entries)


def test_job_listing_defaults():
    job = JobListing(title="Engineer", company="ACME")
    assert job.status == JobStatus.NEW
    assert job.remote is False
    assert job.tech_stack == []
    assert job.requirements == []
    assert job.id != ""
    assert job.created_at != ""


def test_job_status_enum_values():
    assert JobStatus.NEW.value == "NEW"
    assert JobStatus.APPLIED.value == "APPLIED"
    assert JobStatus.OFFERED.value == "OFFERED"
    assert len(list(JobStatus)) >= 6  # at least: NEW, FILTERED, SCORED, APPLIED, REJECTED, OFFERED


def test_application_packet_defaults():
    packet = ApplicationPacket(job_id="test-job-id")
    assert packet.status == PacketStatus.DRAFT
    assert packet.version == 1
    assert packet.qa_answers == {}
    assert packet.id != ""


def test_packet_status_enum():
    assert PacketStatus.DRAFT.value == "DRAFT"
    assert PacketStatus.READY.value == "READY"
    assert PacketStatus.SUBMITTED.value == "SUBMITTED"


def test_candidate_profile_str_strip():
    profile_data = {
        "contact": {"name": "  Test User  ", "email": "  test@example.com  "},
        "skills": [],
    }
    profile = CandidateProfile(**profile_data)
    assert profile.contact.name == "Test User"
    assert profile.contact.email == "test@example.com"
