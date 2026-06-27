"""ATS gap analysis must stay evidence-backed."""
from __future__ import annotations

from job_agent.evidence import EvidenceItem, EvidenceStore
from job_agent.generator.ats_gap import compute_ats_gap
from job_agent.schemas.candidate import CandidateProfile, ContactInfo
from job_agent.schemas.job import JobListing


def _candidate() -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name="Candidate", email="candidate@example.com"),
        skills=[
            {"name": "Python", "category": "language"},
            {"name": "SQL", "category": "data"},
        ],
        target_roles=["Data Scientist"],
        target_locations=["Paris"],
        work_auth_status="non_eu_student_visa",
        can_do_stage=True,
        convention_de_stage_available=True,
    )


def test_ats_gap_names_unbacked_required_keywords(tmp_db):
    evidence = EvidenceStore(
        tmp_db,
        [
            EvidenceItem("skill", "Python", "profile skill", "profile"),
            EvidenceItem("skill", "SQL", "profile skill", "profile"),
        ],
    )
    job = JobListing(
        title="Stage Data Scientist",
        company="ACME",
        requirements=["Required: Python, SQL, Docker"],
        tech_stack=["Python", "SQL", "Docker"],
    )

    gap = compute_ats_gap(job, _candidate(), evidence)

    assert gap.missing_must_haves == ["Docker"]
    assert "Docker" in gap.unsafe_claims_to_avoid
    assert "Docker" not in gap.safe_keywords_to_add


def test_ats_gap_tracks_visible_profile_keywords(tmp_db):
    evidence = EvidenceStore(tmp_db, [EvidenceItem("skill", "Python", "profile skill", "profile")])
    job = JobListing(title="Stage Python Analyst", company="ACME", tech_stack=["Python"])

    gap = compute_ats_gap(job, _candidate(), evidence)

    assert gap.keyword_coverage == 1
    assert gap.already_visible_keywords == ["Python"]
