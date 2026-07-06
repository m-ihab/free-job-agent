"""Career-ops-style A-F evaluation composed from existing local signals.

No new judgment sources: every dimension re-uses the deterministic scorer,
work-authorization router, timing signal, optional preflight coverage, and the
optional local-embedding semantic score. Deterministic and fully offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing
from job_agent.schemas.scoring import ScoreBreakdown
from job_agent.scorer import score_job
from job_agent.timing import job_timing_signal
from job_agent.work_auth import WorkAuthClass, classify_work_auth

if TYPE_CHECKING:
    from job_agent.config import AppConfig

_GRADE_BOUNDS = [(85, "A"), (70, "B"), (55, "C"), (40, "D")]
_FRESHNESS_SCORES = {"fresh": 100, "recent": 80, "aging": 55, "stale_posting": 25, "unknown": 50}
_RECOMMENDATION_BY_DECISION = {"apply": "APPLY", "hold": "REVIEW", "skip": "SKIP"}
_TITLE_STOPWORDS = {"junior", "senior", "lead", "intern", "stage", "alternance", "h/f", "f/h", "de", "la", "le"}


def grade_for_score(score: int) -> str:
    for bound, grade in _GRADE_BOUNDS:
        if score >= bound:
            return grade
    return "F"


@dataclass(frozen=True)
class DimensionGrade:
    name: str
    score: int
    weight: float
    grade: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "score": self.score, "weight": round(self.weight, 4),
                "grade": self.grade, "note": self.note}


@dataclass(frozen=True)
class Evaluation:
    dimensions: list[DimensionGrade]
    overall_score: int
    overall_grade: str
    recommendation: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "overall_grade": self.overall_grade,
            "recommendation": self.recommendation,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "notes": self.notes,
        }

    def to_markdown(self, salary_lines: list[str] | None = None) -> str:
        lines = [
            "# Job evaluation",
            "",
            f"**Overall: {self.overall_grade} ({self.overall_score}/100)** — recommendation: {self.recommendation}",
            "",
            "| Dimension | Grade | Score | Weight | Note |",
            "|---|---|---|---|---|",
        ]
        for dim in self.dimensions:
            lines.append(f"| {dim.name} | {dim.grade} | {dim.score} | {dim.weight:.0%} | {dim.note} |")
        if self.notes:
            lines += ["", "## Notes", *[f"- {note}" for note in self.notes]]
        if salary_lines:
            lines += ["", "## Salary context (local evidence only)", *[f"- {line}" for line in salary_lines]]
        return "\n".join(lines) + "\n"


def _work_auth_dimension(job: JobListing, profile: CandidateProfile) -> DimensionGrade:
    assessment = classify_work_auth(job, profile)
    if assessment.work_auth_class == WorkAuthClass.DIRECTLY_APPLICABLE:
        score = 100
    elif assessment.work_auth_class == WorkAuthClass.SPONSORSHIP_GATED:
        score = 5
    else:
        score = 75
    return DimensionGrade("work_authorization", score, 0.12, grade_for_score(score), assessment.rationale)


def evaluate_job(
    job: JobListing,
    profile: CandidateProfile,
    *,
    breakdown: ScoreBreakdown | None = None,
    preflight: Any | None = None,
    semantic_score: int | None = None,
    config: Any | None = None,
) -> Evaluation:
    """Grade a job A-F across weighted dimensions built from existing signals."""
    if breakdown is None:
        breakdown = score_job(job, profile, semantic_score=semantic_score)
    semantic = semantic_score if semantic_score is not None else breakdown.semantic_score

    # job_timing_signal only reads freshness_recent_hours; the SimpleNamespace
    # stub stands in for AppConfig when no config is supplied.
    timing_config = config if config is not None else SimpleNamespace(freshness_recent_hours=72)
    timing = job_timing_signal(job, cast("AppConfig", timing_config))
    freshness = _FRESHNESS_SCORES.get(timing.bucket, 50)

    dims: list[DimensionGrade] = [
        DimensionGrade("skills", breakdown.skill_score, 0.20, grade_for_score(breakdown.skill_score)),
        DimensionGrade("title", breakdown.title_score, 0.12, grade_for_score(breakdown.title_score)),
        DimensionGrade("location", breakdown.location_score, 0.10, grade_for_score(breakdown.location_score)),
        DimensionGrade("seniority", breakdown.seniority_score, 0.08, grade_for_score(breakdown.seniority_score)),
        DimensionGrade("language", breakdown.language_score, 0.10, grade_for_score(breakdown.language_score)),
        DimensionGrade("salary", breakdown.salary_score, 0.05, grade_for_score(breakdown.salary_score)),
        _work_auth_dimension(job, profile),
        DimensionGrade("freshness", freshness, 0.05, grade_for_score(freshness), timing.reason),
    ]
    if semantic is not None:
        dims.append(DimensionGrade("semantic", int(semantic), 0.08, grade_for_score(int(semantic)),
                                   "local embedding similarity"))
    if preflight is not None:
        coverage = round((preflight.must_have_coverage * 0.6 + preflight.keyword_coverage * 0.4) * 100)
        dims.append(DimensionGrade("evidence", coverage, 0.10, grade_for_score(coverage),
                                   "must-have + ATS keyword coverage backed by local evidence"))

    total_weight = sum(d.weight for d in dims)
    dims = [DimensionGrade(d.name, d.score, d.weight / total_weight, d.grade, d.note) for d in dims]
    overall = round(sum(d.score * d.weight for d in dims))

    notes: list[str] = []
    if "FRENCH_REQUIRED" in breakdown.risk_flags:
        overall = min(overall, 25)
        notes.append("Capped at 25: French required but not in candidate languages.")
    if "SPONSORSHIP_GATED" in breakdown.risk_flags:
        overall = min(overall, 45)
        notes.append("Capped at 45: role appears sponsorship-gated.")

    recommendation = (
        str(preflight.verdict) if preflight is not None
        else _RECOMMENDATION_BY_DECISION.get(breakdown.decision, "REVIEW")
    )
    return Evaluation(
        dimensions=dims,
        overall_score=overall,
        overall_grade=grade_for_score(overall),
        recommendation=recommendation,
        notes=notes,
    )


def _title_tokens(title: str) -> set[str]:
    tokens = {token for token in title.lower().replace("/", " ").split() if len(token) > 2}
    return tokens - _TITLE_STOPWORDS


def salary_comparables(db: Any, job: JobListing, limit: int = 500) -> list[str]:
    """Grounded salary context from already-tracked jobs. Never invents numbers."""
    target_tokens = _title_tokens(job.title)
    midpoints: list[float] = []
    lows: list[int] = []
    highs: list[int] = []
    count = 0
    for tracked in db.list_jobs(limit=limit):
        if tracked.id == job.id or (tracked.salary_min is None and tracked.salary_max is None):
            continue
        if not (target_tokens & _title_tokens(tracked.title)):
            continue
        low = tracked.salary_min if tracked.salary_min is not None else tracked.salary_max
        high = tracked.salary_max if tracked.salary_max is not None else tracked.salary_min
        assert low is not None and high is not None
        lows.append(low)
        highs.append(high)
        midpoints.append((low + high) / 2)
        count += 1
    if not count:
        return ["No local salary evidence yet — track more comparable jobs with posted salaries."]
    midpoints.sort()
    middle = len(midpoints) // 2
    median = midpoints[middle] if len(midpoints) % 2 else (midpoints[middle - 1] + midpoints[middle]) / 2
    lines = [
        f"{count} comparable tracked role(s) with posted salaries.",
        f"Range across comparables: {min(lows):,} - {max(highs):,}.",
        f"Median midpoint: {median:,.0f}.",
    ]
    if job.salary_min is not None or job.salary_max is not None:
        lines.append(f"This posting: {job.salary_min or '?'} - {job.salary_max or '?'} {job.salary_currency}.")
    return lines
