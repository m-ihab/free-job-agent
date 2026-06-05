"""Tests for the scorer module."""
from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing
from job_agent.scorer import ScoreBreakdown, score_job


def test_score_breakdown_fields(sample_job, sample_profile):
    breakdown = score_job(sample_job, sample_profile)
    assert hasattr(breakdown, "skill_score")
    assert hasattr(breakdown, "title_score")
    assert hasattr(breakdown, "location_score")
    assert hasattr(breakdown, "total_score")
    assert hasattr(breakdown, "confidence")
    assert hasattr(breakdown, "decision")
    assert hasattr(breakdown, "notes")
    assert 0 <= breakdown.total_score <= 100
    assert 0 <= breakdown.confidence <= 1


def test_perfect_skill_match_high_score(sample_profile):
    job = JobListing(
        title="Data Scientist Intern",
        company="ACME",
        tech_stack=["python", "sql", "pandas", "machine learning"],
        remote=True,
    )
    breakdown = score_job(job, sample_profile)
    assert breakdown.skill_score > 70


def test_no_skill_match_low_score(sample_profile):
    job = JobListing(
        title="Senior DevOps Engineer",
        company="ACME",
        tech_stack=["rust", "scala", "kubernetes"],
        remote=True,
    )
    breakdown = score_job(job, sample_profile)
    assert breakdown.skill_score < 30


def test_remote_job_remote_ok_high_location_score(sample_profile):
    job = JobListing(title="Engineer", company="ACME", remote=True, tech_stack=[])
    assert sample_profile.remote_ok is True
    breakdown = score_job(job, sample_profile)
    assert breakdown.location_score == 100


def test_non_remote_bad_location_low_score():
    from job_agent.schemas.candidate import ContactInfo
    profile = CandidateProfile(
        contact=ContactInfo(name="Test", email="t@t.com"),
        skills=[],
        target_locations=["San Francisco, CA"],
        remote_ok=False,
        relocation_ok=False,
    )
    job = JobListing(title="Engineer", company="ACME", remote=False, location="Miami, FL", tech_stack=[])
    breakdown = score_job(job, profile)
    assert breakdown.location_score < 50


def test_score_notes_are_populated(sample_job, sample_profile):
    breakdown = score_job(sample_job, sample_profile)
    assert len(breakdown.notes) > 0


def test_score_total_is_weighted_combination(sample_job, sample_profile):
    breakdown = score_job(sample_job, sample_profile)
    expected = round(
        breakdown.skill_score * 0.38
        + breakdown.title_score * 0.22
        + breakdown.location_score * 0.15
        + breakdown.seniority_score * 0.10
        + breakdown.language_score * 0.10
        + breakdown.salary_score * 0.05
    )
    assert breakdown.total_score == expected
