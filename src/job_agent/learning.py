"""Public learning phase API.

This module wraps the local conversion learning helpers with a ranking primitive
that agents and UI code can reuse without mutating job scores.
"""
from __future__ import annotations

from dataclasses import dataclass

from job_agent.conversion_learning import LearningSignal, learned_priority_boost, learning_summary
from job_agent.schemas.job import JobListing


@dataclass(frozen=True)
class LearnedJobRank:
    job: JobListing
    base_score: float
    boost: int
    effective_score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job.id,
            "title": self.job.title,
            "company": self.job.company,
            "base_score": self.base_score,
            "boost": self.boost,
            "effective_score": self.effective_score,
        }


def rank_jobs_with_learning(
    jobs: list[JobListing],
    history: list[JobListing] | None = None,
    *,
    limit: int | None = None,
) -> list[LearnedJobRank]:
    """Return jobs ordered by score plus local outcome-derived boost.

    The input ``fit_score`` fields are left untouched so score calibration stays
    auditable. ``history`` defaults to ``jobs`` for dashboard use.
    """
    historical = history if history is not None else jobs
    ranked: list[LearnedJobRank] = []
    for job in jobs:
        base = float(job.fit_score or 0)
        boost = learned_priority_boost(job, historical)
        ranked.append(LearnedJobRank(job=job, base_score=base, boost=boost, effective_score=min(100.0, base + boost)))
    ranked.sort(key=lambda row: (row.effective_score, row.base_score, row.job.updated_at), reverse=True)
    return ranked[:limit] if limit is not None else ranked


__all__ = ["LearnedJobRank", "LearningSignal", "learned_priority_boost", "learning_summary", "rank_jobs_with_learning"]
