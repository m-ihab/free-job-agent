"""Evidence map coverage and grounding checks."""
from __future__ import annotations

from job_agent.evidence import EvidenceItem, EvidenceStore
from job_agent.generator.evidence_map import build_evidence_map
from job_agent.schemas.job import JobListing


def test_evidence_map_marks_only_supported_keywords_safe(tmp_db):
    evidence = EvidenceStore(
        tmp_db,
        [
            EvidenceItem("skill", "Python", "profile skill", "profile"),
            EvidenceItem("project", "Forecasting API", "Built FastAPI model service with SQL", "cv"),
        ],
    )
    job = JobListing(
        title="Stage Data Scientist",
        company="ACME",
        requirements=["Required: Python, FastAPI, Kubernetes"],
        tech_stack=["Python", "FastAPI", "Kubernetes"],
    )

    result = build_evidence_map(job, evidence)

    assert {"Python", "FastAPI"} <= set(result.safe_keywords_to_add)
    assert "Kubernetes" in result.unsafe_claims_to_avoid
    assert set(result.safe_keywords_to_add).isdisjoint(result.unsafe_claims_to_avoid)


def test_evidence_map_computes_must_have_coverage(tmp_db):
    evidence = EvidenceStore(tmp_db, [EvidenceItem("skill", "Python", "profile skill", "profile")])
    job = JobListing(
        title="Data Engineer",
        company="ACME",
        requirements=["Must have Python", "Must have Docker"],
        description="Nice to have Tableau.",
    )

    result = build_evidence_map(job, evidence)

    assert result.must_have_coverage == 0.5
    assert result.keyword_coverage < 1
    assert any(row.keyword == "Docker" and row.required and not row.supported for row in result.rows)
