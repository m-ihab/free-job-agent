"""Tests for the normalizer module."""

from job_agent.normalizer import (
    _extract_salary,
    _extract_tech_stack,
    _is_remote,
    _extract_lines_after_header,
    normalize,
    SECTION_HEADERS,
)
from job_agent.schemas.job import JobListing


def test_extract_tech_stack_basic():
    text = "We need Python and Docker experience, plus PostgreSQL knowledge."
    found = _extract_tech_stack(text)
    assert "python" in found
    assert "docker" in found
    assert "postgresql" in found


def test_extract_tech_stack_case_insensitive():
    text = "PYTHON developer with REACT skills"
    found = _extract_tech_stack(text)
    assert "python" in found
    assert "react" in found


def test_extract_tech_stack_no_false_positives():
    text = "We are looking for someone with good communication skills."
    found = _extract_tech_stack(text)
    assert "python" not in found


def test_extract_salary_range():
    text = "Salary: $100,000 - $150,000 per year"
    low, high = _extract_salary(text)
    assert low == 100000
    assert high == 150000


def test_extract_salary_single():
    text = "Starting salary $120,000"
    low, high = _extract_salary(text)
    assert low == 120000
    assert high is None


def test_extract_salary_none():
    text = "Competitive compensation based on experience"
    low, high = _extract_salary(text)
    assert low is None
    assert high is None


def test_is_remote_true():
    assert _is_remote("This is a remote position.")
    assert _is_remote("Work from home allowed.")
    assert _is_remote("WFH policy is flexible.")


def test_is_remote_false():
    assert not _is_remote("On-site position in downtown Seattle.")


def test_extract_lines_after_header_requirements():
    text = """Job Description

Requirements:
- 5+ years Python
- Docker experience
- PostgreSQL knowledge

Responsibilities:
- Build APIs
"""
    lines = _extract_lines_after_header(text, SECTION_HEADERS["requirements"])
    assert "5+ years Python" in lines
    assert "Docker experience" in lines
    assert "Build APIs" not in lines


def test_normalize_sets_tech_stack():
    job = JobListing(
        title="Engineer",
        company="ACME",
        raw_text="We need Python and Kubernetes skills.",
    )
    normalized = normalize(job)
    assert "python" in normalized.tech_stack
    assert "kubernetes" in normalized.tech_stack


def test_normalize_sets_title_from_first_line():
    job = JobListing(
        title="[To Be Parsed]",
        company="ACME",
        raw_text="Senior Data Engineer\n\nWe are hiring a data engineer.",
    )
    normalized = normalize(job)
    assert normalized.title == "Senior Data Engineer"


def test_normalize_sets_remote():
    job = JobListing(
        title="Engineer",
        company="ACME",
        raw_text="This is a fully remote position.",
    )
    normalized = normalize(job)
    assert normalized.remote is True


def test_normalize_sets_description():
    job = JobListing(
        title="Engineer",
        company="ACME",
        raw_text="We are a great company.\n\nRequirements:\n- Python",
    )
    normalized = normalize(job)
    assert normalized.description == "We are a great company."
