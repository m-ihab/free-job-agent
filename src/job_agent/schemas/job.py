"""Job listing schemas."""
from __future__ import annotations

from enum import Enum
from typing import Optional
from uuid import uuid4

try:
    from pydantic.v1 import BaseModel, Field
except Exception:  # pragma: no cover
    from pydantic import BaseModel, Field

from job_agent.timeutil import utc_now


class JobStatus(str, Enum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    FILTERED = "FILTERED"
    SCORED = "SCORED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    PACKET_READY = "PACKET_READY"
    APPLYING = "APPLYING"
    ASSISTED_APPLY_OPENED = "ASSISTED_APPLY_OPENED"
    APPLIED = "APPLIED"  # kept for backward compatibility
    MANUALLY_SUBMITTED = "MANUALLY_SUBMITTED"
    REJECTED = "REJECTED"
    INTERVIEW = "INTERVIEW"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"
    FAILED = "FAILED"


class JobListing(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    fingerprint: str = ""
    source: str = "manual"
    source_url: Optional[str] = None
    raw_text: str = ""
    title: str
    company: str
    location: Optional[str] = None
    remote: bool = False
    work_mode: Optional[str] = None
    seniority: Optional[str] = None
    job_type: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = "USD"
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    apply_url: Optional[str] = None
    posted_date: Optional[str] = None
    deadline: Optional[str] = None
    status: JobStatus = JobStatus.NEW
    fit_score: Optional[float] = None
    fit_confidence: Optional[float] = None
    fit_decision: Optional[str] = None
    fit_notes: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

    class Config:
        anystr_strip_whitespace = True
        extra = "allow"
