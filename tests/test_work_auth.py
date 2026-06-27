"""Work-authorization routing for stage/alternance/CDI decisions."""
from __future__ import annotations

import pytest

from job_agent.filters import FilterConfig, apply_filters
from job_agent.schemas.candidate import CandidateProfile, ContactInfo
from job_agent.schemas.job import JobListing
from job_agent.scorer import score_job
from job_agent.work_auth import ContractKind, WorkAuthClass, classify_work_auth, detect_contract_kind


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Stage Data Scientist - Paris", ContractKind.STAGE),
        ("Alternance - Data Analyst RH", ContractKind.ALTERNANCE),
        ("APPRENTISSAGE Ingénieur ML", ContractKind.ALTERNANCE),
        ("CDI Data Engineer", ContractKind.CDI),
        ("CDD Analyste données", ContractKind.CDD),
    ],
)
def test_detect_contract_kind(title: str, expected: ContractKind):
    job = JobListing(title=title, company="ACME", description="")
    assert detect_contract_kind(job) == expected


def _non_eu_student_profile() -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name="Candidate", email="candidate@example.com"),
        skills=[
            {"name": "Python", "category": "language"},
            {"name": "SQL", "category": "data"},
            {"name": "Machine Learning", "category": "ml"},
        ],
        target_roles=["Data Scientist", "Data Analyst"],
        target_locations=["Paris", "France"],
        work_auth_status="non_eu_student_visa",
        can_do_stage=True,
        convention_de_stage_available=True,
        needs_sponsorship_for_cdi=True,
    )


def test_non_eu_student_stage_is_directly_applicable():
    job = JobListing(title="Stage Data Scientist", company="ACME", location="Paris")
    assessment = classify_work_auth(job, _non_eu_student_profile())

    assert assessment.work_auth_class == WorkAuthClass.DIRECTLY_APPLICABLE
    assert assessment.blocking is False
    assert assessment.contract_kind == ContractKind.STAGE


def test_non_eu_student_cdi_is_sponsorship_gated():
    job = JobListing(title="CDI Data Scientist", company="ACME", location="Paris")
    assessment = classify_work_auth(job, _non_eu_student_profile())

    assert assessment.work_auth_class == WorkAuthClass.SPONSORSHIP_GATED
    assert assessment.blocking is True
    assert "sponsorship" in assessment.rationale.lower()


def test_scorer_ranks_stage_above_equivalent_cdi_for_non_eu_student():
    profile = _non_eu_student_profile()
    common = {
        "company": "ACME",
        "location": "Paris",
        "tech_stack": ["Python", "SQL", "Machine Learning"],
        "description": "Python SQL machine learning role in Paris.",
    }
    stage = JobListing(title="Stage Data Scientist", **common)
    cdi = JobListing(title="CDI Data Scientist", **common)

    stage_score = score_job(stage, profile)
    cdi_score = score_job(cdi, profile)

    assert stage_score.total_score > cdi_score.total_score
    assert "SPONSORSHIP_GATED" in cdi_score.risk_flags
    assert "SPONSORSHIP_GATED" not in stage_score.risk_flags


def test_filters_can_hide_sponsorship_gated_roles():
    profile = _non_eu_student_profile()
    job = JobListing(title="CDI Data Scientist", company="ACME", location="Paris")

    result = apply_filters(job, FilterConfig(hide_sponsorship_gated=True), profile)

    assert result.passed is False
    assert result.decision == "reject"
    assert "SPONSORSHIP_GATED" in result.risk_flags
