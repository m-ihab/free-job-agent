"""Timing intelligence for job prioritization."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from job_agent.config import AppConfig
from job_agent.schemas.job import JobListing


@dataclass(frozen=True)
class TimingSignal:
    bucket: str
    age_hours: int | None
    priority_boost: int
    reason: str


def job_timing_signal(job: JobListing, config: AppConfig, *, now: datetime | None = None) -> TimingSignal:
    now = now or datetime.now(timezone.utc)
    posted = _parse_time(job.posted_date or job.created_at)
    if posted is None:
        return TimingSignal("unknown", None, 0, "Posting date unknown")
    age_hours = max(0, int((now - posted).total_seconds() // 3600))
    recent_hours = int(config.freshness_recent_hours or 72)
    if age_hours <= 24:
        return TimingSignal("fresh", age_hours, 90, f"posted {age_hours}h ago")
    if age_hours <= recent_hours:
        return TimingSignal("recent", age_hours, 45, f"posted {age_hours}h ago")
    if age_hours >= 24 * 14:
        return TimingSignal("stale_posting", age_hours, -30, f"posted {age_hours // 24}d ago")
    return TimingSignal("aging", age_hours, 0, f"posted {age_hours}h ago")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        if text.isdigit():
            parsed = datetime.fromtimestamp(int(text), tz=timezone.utc)
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
