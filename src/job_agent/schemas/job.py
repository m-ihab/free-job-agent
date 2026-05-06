"""Job listing schemas."""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(str, Enum):
    NEW = "NEW"
    FILTERED = "FILTERED"
    SCORED = "SCORED"
    PACKET_READY = "PACKET_READY"
    APPLYING = "APPLYING"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"


class JobListing(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    fingerprint: str = ""
    source: str = "manual"
    source_url: Optional[str] = None
    raw_text: str = ""
    title: str
    company: str
    location: Optional[str] = None
    remote: bool = False
    job_type: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = "USD"
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    apply_url: Optional[str] = None
    posted_date: Optional[str] = None
    deadline: Optional[str] = None
    status: JobStatus = JobStatus.NEW
    fit_score: Optional[float] = None
    fit_notes: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
