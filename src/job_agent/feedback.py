"""Local, deterministic thumbs feedback and explainable ranking adjustments."""

from __future__ import annotations

import re
from typing import Protocol, cast

from job_agent.feedback_types import (
    FeedbackAdjustment,
    FeedbackAggregates,
    FeedbackJobRank,
    FeedbackRecord,
    FeedbackVerdict,
    VoteCounts,
)
from job_agent.schemas.job import JobListing
from job_agent.timeutil import utc_now

_TITLE_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")
_TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "in",
    "of",
    "the",
    "to",
    "senior",
    "sr",
    "junior",
    "jr",
}


class FeedbackStore(Protocol):
    def resolve_job(self, job_id_or_prefix: str) -> JobListing | None: ...
    def save_feedback(self, feedback: FeedbackRecord) -> None: ...


def extract_title_keywords(title: str) -> tuple[str, ...]:
    """Return stable, de-duplicated title tokens captured with a rating."""
    seen: set[str] = set()
    keywords: list[str] = []
    for token in _TITLE_TOKEN_RE.findall(title.casefold()):
        if len(token) < 2 or token in _TITLE_STOPWORDS or token in seen:
            continue
        seen.add(token)
        keywords.append(token)
    return tuple(keywords[:8])


def record_feedback(store: FeedbackStore, job_id: str, verdict: str) -> FeedbackRecord:
    if verdict not in {"up", "down"}:
        raise ValueError("Feedback verdict must be 'up' or 'down'.")
    job = store.resolve_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    feedback = FeedbackRecord(
        job_id=job.id,
        verdict=cast(FeedbackVerdict, verdict),
        created_at=utc_now(),
        company=job.company,
        title_keywords=extract_title_keywords(job.title),
        source=job.source,
    )
    store.save_feedback(feedback)
    return feedback


def _add_vote(bucket: dict[str, VoteCounts], key: str, verdict: FeedbackVerdict) -> None:
    normalized = key.strip().casefold()
    if not normalized:
        return
    current = bucket.get(normalized, VoteCounts())
    bucket[normalized] = VoteCounts(
        up=current.up + (verdict == "up"),
        down=current.down + (verdict == "down"),
    )


def aggregate_feedback(records: list[FeedbackRecord]) -> FeedbackAggregates:
    companies: dict[str, VoteCounts] = {}
    keywords: dict[str, VoteCounts] = {}
    sources: dict[str, VoteCounts] = {}
    for record in records:
        _add_vote(companies, record.company, record.verdict)
        _add_vote(sources, record.source, record.verdict)
        for keyword in record.title_keywords:
            _add_vote(keywords, keyword, record.verdict)
    return FeedbackAggregates(companies, keywords, sources)


def _bounded_net(counts: VoteCounts | None, limit: int) -> int:
    net = counts.net if counts else 0
    return max(-limit, min(limit, net))


def _vote_reason(counts: VoteCounts, label: str) -> str:
    if counts.up and counts.down:
        return f"{counts.up} upvote{'s' if counts.up != 1 else ''} and {counts.down} downvote{'s' if counts.down != 1 else ''} {label}"
    count = counts.up or counts.down
    verdict = "upvote" if counts.up else "downvote"
    return f"{count} {verdict}{'s' if count != 1 else ''} {label}"


def calculate_feedback_adjustment(
    job: JobListing,
    aggregates: FeedbackAggregates,
    *,
    base_score: float,
) -> FeedbackAdjustment:
    """Apply company (±2), title (±2), and source (±1) signals after base scoring."""
    reasons: list[str] = []
    company_counts = aggregates.companies.get(job.company.strip().casefold())
    company_delta = _bounded_net(company_counts, 2)
    if company_delta and company_counts:
        reasons.append(_vote_reason(company_counts, "for this company"))

    matched = [
        (key, aggregates.title_keywords[key])
        for key in extract_title_keywords(job.title)
        if key in aggregates.title_keywords
    ]
    title_net = sum(counts.net for _key, counts in matched)
    title_delta = 0
    if title_net:
        magnitude = max(1, int(abs(title_net) / len(matched) + 0.5))
        title_delta = min(2, magnitude) * (1 if title_net > 0 else -1)
        direction = "up" if title_delta > 0 else "down"
        reasons.append(
            f"Matching title keywords lean {direction} ({', '.join(key for key, _counts in matched)})"
        )

    source_counts = aggregates.sources.get(job.source.strip().casefold())
    source_delta = _bounded_net(source_counts, 1)
    if source_delta and source_counts:
        reasons.append(_vote_reason(source_counts, "from this source"))

    raw_delta = max(-5, min(5, company_delta + title_delta + source_delta))
    base = max(0.0, min(100.0, float(base_score)))
    adjusted = max(0.0, min(100.0, base + raw_delta))
    applied_delta = int(round(adjusted - base))
    if applied_delta != raw_delta:
        reasons.append("Final score remains within the 0-100 range")
    if not reasons:
        reasons.append("No matching feedback signals")
    return FeedbackAdjustment(
        base, applied_delta, adjusted, tuple(reasons), company_delta, title_delta, source_delta
    )


def rank_jobs_with_feedback(
    jobs: list[JobListing], records: list[FeedbackRecord], *, limit: int | None = None
) -> list[FeedbackJobRank]:
    aggregates = aggregate_feedback(records)
    ranked: list[FeedbackJobRank] = []
    for job in jobs:
        base = float(job.fit_score or 0)
        adjustment = calculate_feedback_adjustment(job, aggregates, base_score=base)
        ranked.append(
            FeedbackJobRank(
                job, base, adjustment.adjustment, adjustment.adjusted_score, adjustment.reasons
            )
        )
    ranked.sort(
        key=lambda item: (
            item.adjusted_score,
            item.adjustment,
            item.base_score,
            item.job.updated_at,
        ),
        reverse=True,
    )
    return ranked[:limit] if limit is not None else ranked


__all__ = [
    "FeedbackAdjustment",
    "FeedbackAggregates",
    "FeedbackJobRank",
    "FeedbackRecord",
    "VoteCounts",
    "aggregate_feedback",
    "calculate_feedback_adjustment",
    "extract_title_keywords",
    "rank_jobs_with_feedback",
    "record_feedback",
]
