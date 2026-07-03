"""Scoring schemas."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreBreakdown:
    skill_score: int = 0
    title_score: int = 0
    location_score: int = 0
    seniority_score: int = 50
    language_score: int = 50
    salary_score: int = 50
    semantic_score: int | None = None
    total_score: int = 0
    confidence: float = 0.0
    decision: str = "hold"
    notes: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
