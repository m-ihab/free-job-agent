"""Apply-mode enum and event/result DTOs for the auto-apply session."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ApplyMode(str, Enum):
    FILL_AND_CONFIRM = "fill_and_confirm"
    FULL_AUTO = "full_auto"


@dataclass
class ApplyEvent:
    kind: str  # progress | pending_confirm | needs_manual | result | done | error
    job_id: str = ""
    packet_id: str = ""
    message: str = ""
    summary: str = ""
    screenshot_b64: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class ApplyResult:
    job_id: str
    packet_id: str
    status: str  # submitted | skipped | needs_manual | error
    message: str = ""
