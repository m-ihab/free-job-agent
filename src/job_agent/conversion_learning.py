"""Local learning signals derived from the user's own pipeline outcomes."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from job_agent.schemas.job import JobListing, JobStatus

_SUBMITTED = {JobStatus.APPLIED, JobStatus.SUBMITTED, JobStatus.MANUALLY_SUBMITTED}
_REPLIED = {JobStatus.REPLIED, JobStatus.INTERVIEW, JobStatus.INTERVIEWING, JobStatus.OFFERED, JobStatus.OFFER}
_INTERVIEW = {JobStatus.INTERVIEW, JobStatus.INTERVIEWING, JobStatus.OFFERED, JobStatus.OFFER}
_OFFER = {JobStatus.OFFERED, JobStatus.OFFER}


@dataclass(frozen=True)
class LearningSignal:
    label: str
    total: int
    submitted: int
    replies: int
    interviews: int
    offers: int
    avg_score: float
    conversion_rate: float

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def learning_summary(jobs: list[JobListing], *, limit: int = 8) -> dict[str, list[dict[str, object]]]:
    return {
        "sources": [item.to_dict() for item in _signals_by(jobs, _source_label)[:limit]],
        "skills": [item.to_dict() for item in _signals_by(jobs, _skill_labels)[:limit]],
    }


def learned_priority_boost(job: JobListing, jobs: list[JobListing]) -> int:
    if not jobs:
        return 0
    sources = {item.label.casefold(): item for item in _signals_by(jobs, _source_label)}
    skills = {item.label.casefold(): item for item in _signals_by(jobs, _skill_labels)}
    boost = _boost_from_signal(sources.get(_source_label(job).casefold()))
    for skill in _skill_labels(job):
        boost = max(boost, _boost_from_signal(skills.get(skill.casefold())))
    return min(boost, 70)


def _signals_by(jobs: list[JobListing], labeler: Callable[[JobListing], str | Iterable[str]]) -> list[LearningSignal]:
    buckets: dict[str, list[JobListing]] = {}
    for job in jobs:
        labels = labeler(job)
        if isinstance(labels, str):
            labels = [labels]
        for label in labels:
            clean = label.strip()
            if clean:
                buckets.setdefault(clean, []).append(job)
    signals = [_build_signal(label, rows) for label, rows in buckets.items()]
    signals.sort(key=lambda item: (item.conversion_rate, item.submitted, item.avg_score, item.total), reverse=True)
    return signals


def _build_signal(label: str, jobs: list[JobListing]) -> LearningSignal:
    total = len(jobs)
    submitted = sum(1 for job in jobs if job.status in _SUBMITTED or job.status in _REPLIED)
    replies = sum(1 for job in jobs if job.status in _REPLIED)
    interviews = sum(1 for job in jobs if job.status in _INTERVIEW)
    offers = sum(1 for job in jobs if job.status in _OFFER)
    scores = [float(job.fit_score) for job in jobs if job.fit_score is not None]
    return LearningSignal(
        label=label,
        total=total,
        submitted=submitted,
        replies=replies,
        interviews=interviews,
        offers=offers,
        avg_score=round(sum(scores) / len(scores), 1) if scores else 0.0,
        conversion_rate=_rate(replies + interviews + offers, submitted or total),
    )


def _source_label(job: JobListing) -> str:
    return (job.source or "manual").strip() or "manual"


def _skill_labels(job: JobListing) -> list[str]:
    return sorted({str(skill).strip() for skill in job.tech_stack if str(skill).strip()})[:12]


def _boost_from_signal(signal: LearningSignal | None) -> int:
    if signal is None or signal.submitted == 0:
        return 0
    if signal.conversion_rate >= 0.75:
        return 60
    if signal.conversion_rate >= 0.5:
        return 45
    if signal.conversion_rate >= 0.25:
        return 25
    return 10 if signal.interviews or signal.offers else 0


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 2) if denominator else 0.0
