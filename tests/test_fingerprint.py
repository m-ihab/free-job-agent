"""Tests for fingerprinting."""

from job_agent.fingerprint import compute_fingerprint, set_fingerprint
from job_agent.schemas.job import JobListing


def test_same_job_same_fingerprint():
    job = JobListing(
        title="Engineer",
        company="ACME",
        location="NYC",
        description="Build software",
    )
    fp1 = compute_fingerprint(job)
    fp2 = compute_fingerprint(job)
    assert fp1 == fp2


def test_different_jobs_different_fingerprints():
    job1 = JobListing(title="Engineer", company="ACME", description="Build software")
    job2 = JobListing(title="Manager", company="ACME", description="Manage projects")
    assert compute_fingerprint(job1) != compute_fingerprint(job2)


def test_fingerprint_is_hex_string():
    job = JobListing(title="Engineer", company="ACME")
    fp = compute_fingerprint(job)
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_set_fingerprint_updates_job():
    job = JobListing(title="Engineer", company="ACME")
    assert job.fingerprint == ""
    updated = set_fingerprint(job)
    assert updated.fingerprint != ""
    assert len(updated.fingerprint) == 64


def test_fingerprint_different_company():
    job1 = JobListing(title="Engineer", company="ACME")
    job2 = JobListing(title="Engineer", company="TechCorp")
    assert compute_fingerprint(job1) != compute_fingerprint(job2)


def test_fingerprint_normalized_case():
    """Fingerprint should be stable regardless of case."""
    job1 = JobListing(title="ENGINEER", company="ACME")
    job2 = JobListing(title="engineer", company="acme")
    assert compute_fingerprint(job1) == compute_fingerprint(job2)
