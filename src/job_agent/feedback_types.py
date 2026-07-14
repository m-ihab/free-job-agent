"""Value objects used by the deterministic feedback ranker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from job_agent.schemas.job import JobListing

FeedbackVerdict = Literal["up", "down"]


@dataclass(frozen=True)
class FeedbackRecord:
    job_id: str
    verdict: FeedbackVerdict
    created_at: str
    company: str
    title_keywords: tuple[str, ...]
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "verdict": self.verdict,
            "created_at": self.created_at,
            "company": self.company,
            "title_keywords": list(self.title_keywords),
            "source": self.source,
        }


@dataclass(frozen=True)
class VoteCounts:
    up: int = 0
    down: int = 0

    @property
    def net(self) -> int:
        return self.up - self.down


@dataclass(frozen=True)
class FeedbackAggregates:
    companies: dict[str, VoteCounts] = field(default_factory=dict)
    title_keywords: dict[str, VoteCounts] = field(default_factory=dict)
    sources: dict[str, VoteCounts] = field(default_factory=dict)


@dataclass(frozen=True)
class FeedbackAdjustment:
    base_score: float
    adjustment: int
    adjusted_score: float
    reasons: tuple[str, ...]
    company_adjustment: int
    title_adjustment: int
    source_adjustment: int

    def to_dict(self) -> dict[str, object]:
        return {
            "base_score": self.base_score,
            "feedback_adjustment": self.adjustment,
            "adjusted_score": self.adjusted_score,
            "feedback_reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class FeedbackJobRank:
    job: JobListing
    base_score: float
    adjustment: int
    adjusted_score: float
    reasons: tuple[str, ...]
