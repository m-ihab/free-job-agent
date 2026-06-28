from __future__ import annotations

from job_agent.learning import rank_jobs_with_learning
from job_agent.schemas.job import JobListing, JobStatus


def test_rank_jobs_with_learning_boosts_successful_sources_without_mutating_scores():
    history = [
        JobListing(title="ML Intern", company="A", source="France Travail", status=JobStatus.MANUALLY_SUBMITTED, fit_score=70, tech_stack=["Python"]),
        JobListing(title="ML Intern", company="B", source="France Travail", status=JobStatus.REPLIED, fit_score=72, tech_stack=["Python"]),
        JobListing(title="BI Intern", company="C", source="manual", status=JobStatus.REJECTED, fit_score=90, tech_stack=["Tableau"]),
    ]
    target = JobListing(title="Python Intern", company="D", source="France Travail", fit_score=65, tech_stack=["Python"])

    ranked = rank_jobs_with_learning([target], history)

    assert ranked[0].job is target
    assert ranked[0].boost > 0
    assert ranked[0].effective_score > target.fit_score
    assert target.fit_score == 65
