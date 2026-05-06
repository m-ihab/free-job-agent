"""Tests for the scorer module."""
import pytest

from job_agent.schemas.candidate import CandidateProfile, Skill
from job_agent.schemas.job import JobListing
from job_agent.scorer import ScoreBreakdown, score_job


def test_score_breakdown_fields(sample_job, sample_profile):
    breakdown = score_job(sample_job, sample_profile)
    assert hasattr(breakdown, "skill_score")
    assert hasattr(breakdown, "title_score")
    assert hasattr(breakdown, "location_score")
    assert hasattr(breakdown, "total_score")
    assert hasattr(breakdown, "notes")
    assert 0.0 <= breakdown.total_score <= 1.0


def test_perfect_skill_match_high_score(sample_profile):
    """Job that matches all skills should score high."""
    job = JobListing(
        title="Senior Software Engineer",
        company="ACME",
        tech_stack=["python", "fastapi", "postgresql", "docker"],
        remote=True,
    )
    breakdown = score_job(job, sample_profile)
    assert breakdown.skill_score > 0.7


def test_no_skill_match_low_score(sample_profile):
    """Job with completely different stack should score low on skills."""
    job = JobListing(
        title="iOS Developer",
        company="ACME",
        tech_stack=["swift", "xcode", "objective-c"],
        remote=True,
    )
    breakdown = score_job(job, sample_profile)
    assert breakdown.skill_score < 0.3


def test_remote_job_remote_ok_high_location_score(sample_profile):
    """Remote job with remote_ok profile should get max location score."""
    job = JobListing(
        title="Engineer",
        company="ACME",
        remote=True,
        tech_stack=[],
    )
    assert sample_profile.remote_ok is True
    breakdown = score_job(job, sample_profile)
    assert breakdown.location_score == 1.0


def test_non_remote_bad_location_low_score():
    """Non-remote job in unwanted location should score low."""
    from job_agent.schemas.candidate import ContactInfo
    profile = CandidateProfile(
        contact=ContactInfo(name="Test", email="t@t.com"),
        skills=[],
        target_locations=["San Francisco, CA"],
        remote_ok=False,
        relocation_ok=False,
    )
    job = JobListing(
        title="Engineer",
        company="ACME",
        remote=False,
        location="Miami, FL",
        tech_stack=[],
    )
    breakdown = score_job(job, profile)
    assert breakdown.location_score < 0.5


def test_score_notes_are_populated(sample_job, sample_profile):
    breakdown = score_job(sample_job, sample_profile)
    assert len(breakdown.notes) > 0


def test_score_total_is_weighted_combination(sample_job, sample_profile):
    breakdown = score_job(sample_job, sample_profile)
    expected = (
        breakdown.skill_score * 0.5
        + breakdown.title_score * 0.3
        + breakdown.location_score * 0.2
    )
    assert abs(breakdown.total_score - round(expected, 3)) < 0.001
