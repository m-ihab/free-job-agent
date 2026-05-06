"""Tests for the filters module."""
import pytest

from job_agent.filters import FilterConfig, FilterResult, apply_filters
from job_agent.schemas.job import JobListing


def test_empty_config_passes_all(sample_job):
    config = FilterConfig()
    result = apply_filters(sample_job, config)
    assert result.passed is True
    assert result.reasons == []


def test_blocked_company_fails(sample_job):
    config = FilterConfig(blocked_companies=["TechCorp Inc."])
    result = apply_filters(sample_job, config)
    assert result.passed is False
    assert any("Blocked company" in r for r in result.reasons)


def test_blocked_company_fuzzy(sample_job):
    config = FilterConfig(blocked_companies=["TechCorp"])
    result = apply_filters(sample_job, config)
    assert result.passed is False


def test_blocked_keyword_fails(sample_job):
    config = FilterConfig(blocked_keywords=["fastapi"])
    result = apply_filters(sample_job, config)
    assert result.passed is False
    assert any("Blocked keyword" in r for r in result.reasons)


def test_required_keyword_missing_fails():
    job = JobListing(title="Engineer", company="ACME", description="Java developer role")
    config = FilterConfig(required_keywords=["python"])
    result = apply_filters(job, config)
    assert result.passed is False
    assert any("Missing required keyword" in r for r in result.reasons)


def test_required_keyword_present_passes():
    job = JobListing(title="Engineer", company="ACME", description="Python developer role")
    config = FilterConfig(required_keywords=["python"])
    result = apply_filters(job, config)
    assert result.passed is True


def test_remote_only_filter_fails():
    job = JobListing(title="Engineer", company="ACME", remote=False, location="NYC")
    config = FilterConfig(remote_only=True)
    result = apply_filters(job, config)
    assert result.passed is False
    assert any("not remote" in r for r in result.reasons)


def test_remote_only_filter_passes(sample_job):
    # sample_job has remote=True
    config = FilterConfig(remote_only=True)
    result = apply_filters(sample_job, config)
    assert result.passed is True


def test_salary_filter_fails():
    job = JobListing(title="Engineer", company="ACME", salary_max=80000)
    config = FilterConfig(min_salary=100000)
    result = apply_filters(job, config)
    assert result.passed is False
    assert any("Salary too low" in r for r in result.reasons)


def test_salary_filter_passes():
    job = JobListing(title="Engineer", company="ACME", salary_max=150000)
    config = FilterConfig(min_salary=100000)
    result = apply_filters(job, config)
    assert result.passed is True


def test_multiple_failures():
    job = JobListing(title="Engineer", company="ACME", remote=False, salary_max=50000)
    config = FilterConfig(remote_only=True, min_salary=100000)
    result = apply_filters(job, config)
    assert result.passed is False
    assert len(result.reasons) >= 2
