from __future__ import annotations

from job_agent.evidence import EvidenceItem, EvidenceStore
from job_agent.generator.reverse_jd import analyze_reverse_jd, render_reverse_jd_markdown
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, Skill
from job_agent.schemas.job import JobListing


def test_reverse_jd_separates_supported_and_missing_keywords(tmp_db):
    profile = CandidateProfile(contact=ContactInfo(name="Candidate", email="c@example.com"), skills=[Skill(name="Python")])
    evidence = EvidenceStore(tmp_db, [EvidenceItem("skill", "Python", "programming", "profile")])
    job = JobListing(
        title="Machine Learning Intern",
        company="Acme",
        description="Python, SQL and MLOps required",
        tech_stack=["Python", "SQL", "MLOps"],
        requirements=["Python required", "MLOps required"],
    )

    result = analyze_reverse_jd(job, profile, evidence)
    markdown = render_reverse_jd_markdown(job, profile, evidence)

    assert "Python" in result.matched_keywords
    assert "MLOps" in result.missing_keywords
    assert result.recommendation
    assert "Do not claim unsupported" in markdown
