"""Application preflight verdicts."""
from __future__ import annotations

from job_agent.config import AppConfig
from job_agent.evidence import EvidenceItem, EvidenceStore
from job_agent.generator.preflight import run_preflight
from job_agent.schemas.candidate import CandidateProfile, ContactInfo
from job_agent.schemas.job import JobListing


def _candidate() -> CandidateProfile:
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
        min_fit_score=70,
    )


def _config(tmp_path) -> AppConfig:
    return AppConfig(data_dir=tmp_path / "data", cover_letter_auto_threshold=70)


def _evidence(tmp_db, *extra: EvidenceItem) -> EvidenceStore:
    return EvidenceStore(
        tmp_db,
        [
            EvidenceItem("skill", "Python", "profile skill", "profile"),
            EvidenceItem("skill", "SQL", "profile skill", "profile"),
            EvidenceItem("skill", "Machine Learning", "profile skill", "profile"),
            *extra,
        ],
    )


def test_preflight_high_fit_grounded_stage_applies(tmp_db, tmp_path):
    job = JobListing(
        title="Stage Data Scientist",
        company="ACME",
        location="Paris",
        description="Python SQL machine learning internship in Paris.",
        requirements=["Required: Python, SQL, Machine Learning"],
        tech_stack=["Python", "SQL", "Machine Learning"],
    )

    result = run_preflight(job, _candidate(), _evidence(tmp_db), _config(tmp_path))

    assert result.verdict == "APPLY"
    assert result.fit_score >= 70
    assert result.must_have_coverage == 1
    assert result.unsafe_claims_to_avoid == []


def test_preflight_unbacked_must_have_is_named(tmp_db, tmp_path):
    job = JobListing(
        title="Stage Data Scientist",
        company="ACME",
        location="Paris",
        requirements=["Required: Python, SQL, Kubernetes"],
        tech_stack=["Python", "SQL", "Kubernetes"],
    )

    result = run_preflight(job, _candidate(), _evidence(tmp_db), _config(tmp_path))

    assert result.verdict in {"APPLY_WITH_EDITS", "SKIP"}
    assert "Kubernetes" in result.missing_must_haves
    assert "Kubernetes" in result.unsafe_claims_to_avoid
    assert "Kubernetes" not in result.safe_keywords_to_add


def test_preflight_unknown_screening_question_needs_manual(tmp_db, tmp_path):
    job = JobListing(
        title="Stage Data Scientist",
        company="ACME",
        location="Paris",
        description="Screening: Are you available to start in September 2026?",
        requirements=["Required: Python, SQL"],
        tech_stack=["Python", "SQL"],
    )

    result = run_preflight(job, _candidate(), _evidence(tmp_db), _config(tmp_path))

    assert result.verdict == "NEEDS_MANUAL"
    assert result.unknown_screening_answers == ["Are you available to start in September 2026?"]
    assert result.application_effort == "high"
