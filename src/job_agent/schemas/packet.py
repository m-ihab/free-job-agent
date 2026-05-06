"""Application packet schemas."""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class PacketStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    SUBMITTED = "SUBMITTED"


class ApplicationPacket(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    version: int = 1
    status: PacketStatus = PacketStatus.DRAFT
    tailored_cv_md: str = ""
    tailored_cv_html: str = ""
    tailored_cv_pdf_path: Optional[str] = None
    cover_letter_md: str = ""
    cover_letter_html: str = ""
    cover_letter_pdf_path: Optional[str] = None
    qa_answers: dict[str, str] = Field(default_factory=dict)
    assistant_page_html: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
