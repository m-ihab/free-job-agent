"""Application packet schemas."""
from __future__ import annotations

from enum import Enum
from typing import Optional
from uuid import uuid4

try:
    from pydantic.v1 import BaseModel, Field
except Exception:  # pragma: no cover
    from pydantic import BaseModel, Field  # type: ignore[assignment]

from job_agent.timeutil import utc_now


class PacketStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ASSISTED_APPLY_OPENED = "ASSISTED_APPLY_OPENED"
    SUBMITTED = "SUBMITTED"  # backward-compatible alias
    MANUALLY_SUBMITTED = "MANUALLY_SUBMITTED"
    AUTO_SUBMITTED = "AUTO_SUBMITTED"  # FULL_AUTO submitted without per-job confirmation
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class DocumentArtifact(BaseModel):
    kind: str
    path: str
    sha256: str
    created_at: str = Field(default_factory=utc_now)

    class Config:
        anystr_strip_whitespace = True
        extra = "forbid"


class ScreeningAnswer(BaseModel):
    question: str
    answer: str
    source: str = "master_qa_profile"
    confidence: float = Field(default=1.0, ge=0, le=1)
    needs_review: bool = False

    class Config:
        anystr_strip_whitespace = True
        extra = "forbid"


class ApplicationPacket(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    job_fingerprint: str = ""
    version: int = 1
    status: PacketStatus = PacketStatus.DRAFT
    fit_score: Optional[float] = None
    fit_confidence: Optional[float] = None
    fit_decision: Optional[str] = None
    fit_notes: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    profile_hash: Optional[str] = None
    master_cv_hash: Optional[str] = None
    qa_profile_hash: Optional[str] = None
    artifacts: list[DocumentArtifact] = Field(default_factory=list)
    screening_answers: list[ScreeningAnswer] = Field(default_factory=list)

    # Backward-compatible content/path fields used by existing tests and CLI output.
    tailored_cv_md: str = ""
    tailored_cv_html: str = ""
    tailored_cv_pdf_path: Optional[str] = None
    cover_letter_md: str = ""
    cover_letter_html: str = ""
    cover_letter_pdf_path: Optional[str] = None
    qa_answers: dict[str, str] = Field(default_factory=dict)
    assistant_page_html: str = ""
    # Per-application brief: a one-line headline, a short summary, and the role's
    # most relevant keywords. Grounded in profile+job fields (never invented).
    headline: str = ""
    summary: str = ""
    keywords: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

    class Config:
        anystr_strip_whitespace = True
        extra = "forbid"
