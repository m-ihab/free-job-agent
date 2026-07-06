"""Pipeline / conversion cockpit helpers."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from job_agent.config import AppConfig
from job_agent.conversion_learning import learned_priority_boost
from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.timing import job_timing_signal

_TERMINAL = {
    JobStatus.REJECTED,
    JobStatus.WITHDRAWN,
    JobStatus.ACCEPTED,
    JobStatus.FAILED,
}
_SUBMITTED = {JobStatus.APPLIED, JobStatus.SUBMITTED, JobStatus.MANUALLY_SUBMITTED, JobStatus.AUTO_SUBMITTED}
_INTERVIEW = {JobStatus.INTERVIEW, JobStatus.INTERVIEWING}
_OFFER = {JobStatus.OFFERED, JobStatus.OFFER}


@dataclass(frozen=True)
class PipelineAction:
    job_id: str
    title: str
    company: str
    status: str
    stage: str
    action: str
    reason: str
    priority: int
    fit_score: float | None


@dataclass(frozen=True)
class StaleJob:
    job_id: str
    title: str
    company: str
    status: str
    days_idle: int
    next_action: str


@dataclass(frozen=True)
class ConversionMetrics:
    total: int
    stage_counts: dict[str, int]
    submitted: int
    replied: int
    interviews: int
    offers: int
    submitted_rate: float
    reply_rate: float
    interview_rate: float
    offer_rate: float

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def pipeline_stage(job: JobListing) -> str:
    status = job.status
    if status in {JobStatus.NEW, JobStatus.DISCOVERED}:
        return "DISCOVERED"
    if status in {JobStatus.SCORED, JobStatus.NEEDS_REVIEW, JobStatus.QUALIFIED}:
        return "QUALIFIED"
    if status == JobStatus.PACKET_READY:
        return "PACKET_READY"
    if status in {JobStatus.OUTREACH_DRAFTED, JobStatus.OUTREACH_SENT}:
        return status.value
    if status in {JobStatus.APPLYING, JobStatus.APPLY_ATTEMPTED, JobStatus.ASSISTED_APPLY_OPENED}:
        return "APPLY_ATTEMPTED"
    if status in _SUBMITTED:
        return "SUBMITTED"
    if status == JobStatus.NEEDS_MANUAL:
        return "NEEDS_MANUAL"
    if status in {JobStatus.FOLLOWUP_DUE, JobStatus.FOLLOWUP_SENT, JobStatus.REPLIED}:
        return status.value
    if status in _INTERVIEW:
        return "INTERVIEWING"
    if status in _OFFER:
        return "OFFER"
    return status.value


def next_best_action(job: JobListing, config: AppConfig, now: datetime | None = None) -> PipelineAction:
    now = now or datetime.now(timezone.utc)
    stage = pipeline_stage(job)
    days = _days_since(job.updated_at or job.created_at, now)
    priority = int(job.fit_score or 0)
    action = "Review"
    reason = "Review this job and choose the next step."

    if job.status == JobStatus.NEEDS_MANUAL:
        action, reason, priority = "Finish manual apply", "Full Auto handed this job off for human review.", 1000
    elif job.status in {JobStatus.NEW, JobStatus.DISCOVERED}:
        action, reason, priority = "Run preflight", "Check fit, evidence, work authorization, and manual blockers.", 780
    elif job.status in {JobStatus.SCORED, JobStatus.QUALIFIED, JobStatus.NEEDS_REVIEW}:
        action, reason, priority = "Tailor CV", "Generate the packet or fix the preflight gaps.", 760
    elif job.status == JobStatus.PACKET_READY:
        action, reason, priority = "Apply", "Packet is ready; submit or send an outreach/referral ask.", 850
    elif job.status in _SUBMITTED:
        if days >= 7:
            action, reason, priority = "Send follow-up", f"No movement for {days} days after submission.", 960
        else:
            action, reason, priority = "Wait", "Recently submitted; wait before nudging.", 350
    elif job.status in _INTERVIEW:
        action, reason, priority = "Prepare interview", "Interview stage; build STAR stories and objection handling.", 930
    elif job.status in _OFFER:
        action, reason, priority = "Review offer", "Offer received; compare terms and next steps.", 950
    elif job.status in _TERMINAL:
        action, reason, priority = "No action", "Terminal status.", 0

    timing = job_timing_signal(job, config, now=now)
    if job.status not in _TERMINAL and timing.priority_boost:
        priority += timing.priority_boost
        if timing.priority_boost > 0:
            reason = f"{reason} Fresh posting: {timing.reason}."
        else:
            reason = f"{reason} Older posting: {timing.reason}."

    if job.status not in _TERMINAL and days >= int(config.stale_days or 14):
        priority += 80
        if action in {"Wait", "Review"}:
            action = "Revive or close"
            reason = f"No movement for {days} days."

    return PipelineAction(job.id, job.title, job.company, job.status.value, stage, action, reason, priority, job.fit_score)


def build_today_queue(
    jobs: list[JobListing],
    config: AppConfig,
    *,
    now: datetime | None = None,
    limit: int = 10,
) -> list[PipelineAction]:
    now = now or datetime.now(timezone.utc)
    actions = [
        replace(action, priority=action.priority + learned_priority_boost(job, jobs))
        for job in jobs
        for action in [next_best_action(job, config, now)]
    ]
    actionable = [item for item in actions if item.action != "No action"]
    actionable.sort(key=lambda item: (item.priority, item.fit_score or 0), reverse=True)
    return actionable[:limit]


def detect_stale(jobs: list[JobListing], config: AppConfig, *, now: datetime | None = None) -> list[StaleJob]:
    now = now or datetime.now(timezone.utc)
    threshold = int(config.stale_days or 14)
    stale: list[StaleJob] = []
    for job in jobs:
        if job.status in _TERMINAL:
            continue
        days = _days_since(job.updated_at or job.created_at, now)
        if days >= threshold:
            action = next_best_action(job, config, now)
            stale.append(StaleJob(job.id, job.title, job.company, job.status.value, days, action.action))
    stale.sort(key=lambda item: item.days_idle, reverse=True)
    return stale


def conversion_metrics(jobs: list[JobListing]) -> ConversionMetrics:
    stage_counts: dict[str, int] = {}
    for job in jobs:
        stage = pipeline_stage(job)
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    total = len(jobs)
    submitted = sum(1 for job in jobs if job.status in _SUBMITTED or job.status in _INTERVIEW or job.status in _OFFER)
    replied = sum(1 for job in jobs if job.status in {JobStatus.REPLIED} or job.status in _INTERVIEW or job.status in _OFFER)
    interviews = sum(1 for job in jobs if job.status in _INTERVIEW or job.status in _OFFER)
    offers = sum(1 for job in jobs if job.status in _OFFER)
    return ConversionMetrics(
        total=total,
        stage_counts=stage_counts,
        submitted=submitted,
        replied=replied,
        interviews=interviews,
        offers=offers,
        submitted_rate=_rate(submitted, total),
        reply_rate=_rate(replied, submitted),
        interview_rate=_rate(interviews, submitted),
        offer_rate=_rate(offers, submitted),
    )


def set_job_notes(config: AppConfig, job_id: str, notes: str) -> None:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = db.resolve_job(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    if not db.update_job_notes(job.id, notes):
        raise ValueError(f"Job not found: {job_id}")
    db.log_event(job.id, "NOTES_UPDATED", {"notes": notes})


def get_job_notes(config: AppConfig, job_id: str) -> str:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = db.resolve_job(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    return job.notes or ""


def _days_since(value: str, now: datetime) -> int:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int((now - parsed).total_seconds() // 86400))


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 2)
