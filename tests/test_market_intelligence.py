"""Tests for job market intelligence aggregation."""
from __future__ import annotations

from job_agent.market_intelligence import MarketReport, build_market_report
from job_agent.schemas.job import JobListing


def _job(**overrides) -> JobListing:
    base = dict(title="Data Scientist", company="ACME")
    base.update(overrides)
    return JobListing(**base)


def test_empty_input_returns_zeroed_report_without_dividing_by_zero():
    report = build_market_report([])

    assert isinstance(report, MarketReport)
    assert report.total_jobs == 0
    assert report.top_skills == []
    assert report.remote_pct == 0


def test_top_skills_counts_tech_stack_occurrences():
    jobs = [
        _job(tech_stack=["python", "sql"]),
        _job(tech_stack=["python"], company="B"),
    ]

    report = build_market_report(jobs)

    assert dict(report.top_skills)["python"] == 2
    assert dict(report.top_skills)["sql"] == 1


def test_contract_breakdown_classifies_french_and_english_terms():
    jobs = [
        _job(job_type="Stage 6 mois"),
        _job(job_type="Alternance", company="B"),
        _job(job_type="CDI", company="C"),
        _job(job_type="CDD", company="D"),
        _job(job_type="freelance mission", company="E"),
    ]

    breakdown = build_market_report(jobs).contract_breakdown

    assert breakdown["Stage / Internship"] == 1
    assert breakdown["Alternance"] == 1
    assert breakdown["CDI / Permanent"] == 1
    assert breakdown["CDD / Fixed-term"] == 1
    assert breakdown["Other / Unknown"] == 1


def test_remote_and_language_percentages():
    jobs = [
        _job(remote=True, languages=["French"]),
        _job(remote=False, languages=["English"], company="B"),
    ]

    report = build_market_report(jobs)

    assert report.remote_pct == 50.0
    assert report.language_requirement_pct == 50.0


def test_salary_range_ignores_missing_values():
    jobs = [
        _job(salary_min=40000, salary_max=55000),
        _job(salary_min=None, salary_max=70000, company="B"),
    ]

    assert build_market_report(jobs).salary_range == (40000, 70000)


def test_match_rate_only_computed_when_profile_skills_supplied():
    jobs = [_job(tech_stack=["python"]), _job(tech_stack=["rust"], company="B")]

    without = build_market_report(jobs)
    withp = build_market_report(jobs, profile_skills={"Python"})

    assert without.your_match_rate == 0
    assert withp.your_match_rate == 50.0  # 1 of 2 jobs shares a skill


def test_to_markdown_renders_core_sections():
    report = build_market_report(
        [_job(tech_stack=["python"], seniority="senior")],
        profile_skills={"python"},
    )

    md = report.to_markdown()

    assert "# Job Market Intelligence Report" in md
    assert "Top In-Demand Skills" in md
    assert "Seniority Breakdown" in md
