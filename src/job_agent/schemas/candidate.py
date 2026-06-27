"""Candidate, CV, and screening-answer schemas.

These models intentionally accept the original Copilot example format while also
supporting stricter fields needed for traceable application packets.
"""
from __future__ import annotations

from typing import Any, Optional, Union
from uuid import uuid4

try:
    from pydantic.v1 import BaseModel, Field, root_validator, validator
except Exception:  # pragma: no cover
    from pydantic import (  # type: ignore[assignment,no-redef]
        BaseModel,
        Field,
        root_validator,
        validator,
    )


class _Base(BaseModel):
    class Config:
        anystr_strip_whitespace = True
        extra = "allow"


class ContactInfo(_Base):
    name: str
    email: str
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    work_authorization: Optional[str] = None


class Preferences(_Base):
    target_roles: list[str] = Field(default_factory=list)
    target_locations: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    hybrid_ok: bool = True
    onsite_ok: bool = False
    relocation_ok: bool = False
    excluded_companies: list[str] = Field(default_factory=list)
    preferred_companies: list[str] = Field(default_factory=list)
    min_fit_score: int = Field(default=70, ge=0, le=100)
    max_applications_per_day: int = Field(default=15, ge=1, le=200)
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None


class Education(_Base):
    institution: str
    degree: str
    field: str = ""
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    gpa: Optional[float] = None
    honors: list[str] = Field(default_factory=list)
    location: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class WorkExperience(_Base):
    company: str
    title: str
    start_date: str
    end_date: Optional[str] = None
    location: Optional[str] = None
    bullet_points: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Project(_Base):
    name: str
    description: str
    url: Optional[str] = None
    technologies: list[str] = Field(default_factory=list)
    bullet_points: list[str] = Field(default_factory=list)


class Certification(_Base):
    name: str
    issuer: str
    year: Optional[int] = None
    url: Optional[str] = None


class Skill(_Base):
    name: str
    category: str = "general"
    years_experience: Optional[float] = None


class CandidateProfile(_Base):
    contact: ContactInfo
    summary: str = ""
    skills: list[Skill] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    work_authorizations: list[str] = Field(default_factory=list)
    work_auth_status: str = ""
    can_do_stage: bool = False
    convention_de_stage_available: bool = False
    needs_sponsorship_for_cdi: bool = False
    visa_expiry: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    target_roles: list[str] = Field(default_factory=list)
    target_locations: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    hybrid_ok: bool = True
    onsite_ok: bool = False
    relocation_ok: bool = False
    excluded_companies: list[str] = Field(default_factory=list)
    preferred_companies: list[str] = Field(default_factory=list)
    min_fit_score: int = Field(default=70, ge=0, le=100)
    preferences: Optional[Preferences] = None

    @root_validator(pre=True)
    def merge_preferences(cls, values: dict[str, Any]) -> dict[str, Any]:
        prefs = values.get("preferences") or {}
        if isinstance(prefs, dict):
            for key in [
                "target_roles", "target_locations", "remote_ok", "hybrid_ok",
                "onsite_ok", "relocation_ok", "excluded_companies",
                "preferred_companies", "min_fit_score", "salary_min", "salary_max",
                "max_applications_per_day",
            ]:
                if key in prefs and key not in values:
                    values[key] = prefs[key]
        return values

    @root_validator
    def validate_salary_range(cls, values: dict[str, Any]) -> dict[str, Any]:
        low, high = values.get("salary_min"), values.get("salary_max")
        if low is not None and high is not None and low > high:
            raise ValueError("salary_min cannot be greater than salary_max")
        return values

    def all_skill_names(self) -> list[str]:
        names = [s.name for s in self.skills]
        return sorted({n.strip() for n in names if n and n.strip()}, key=str.lower)


class CVSection(_Base):
    title: str
    content: list[str] = Field(default_factory=list)


class MasterCV(_Base):
    contact: ContactInfo
    summary: str = ""
    education: list[Education] = Field(default_factory=list)
    experience: list[WorkExperience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    max_experience_bullets_per_role: int = Field(default=4, ge=1, le=10)
    max_projects: int = Field(default=3, ge=0, le=10)

    def all_skill_names(self) -> list[str]:
        names = [s.name for s in self.skills]
        for exp in self.experience:
            names.extend(exp.technologies)
        for proj in self.projects:
            names.extend(proj.technologies)
        return sorted({n.strip() for n in names if n and n.strip()}, key=str.lower)


AnswerValue = Union[str, bool, int, float]


class QAEntry(_Base):
    id: str = Field(default_factory=lambda: f"qa_{uuid4().hex[:10]}")
    question_patterns: list[str] = Field(default_factory=list)
    answer: AnswerValue
    category: str = "general"
    jurisdiction: Optional[str] = None
    locked: bool = True
    sensitive: bool = False
    notes: Optional[str] = None

    @root_validator(pre=True)
    def accept_legacy_question_pattern(cls, values: dict[str, Any]) -> dict[str, Any]:
        if "question_pattern" in values and "question_patterns" not in values:
            values["question_patterns"] = [values.pop("question_pattern")]
        return values

    @validator("question_patterns")
    def require_patterns(cls, value: list[str]) -> list[str]:
        cleaned = [v.strip() for v in value if v and v.strip()]
        if not cleaned:
            raise ValueError("QA entries require at least one question pattern")
        return cleaned

    @property
    def question_pattern(self) -> str:
        return self.question_patterns[0]


class QAProfile(_Base):
    entries: list[QAEntry] = Field(default_factory=list)
    hold_if_missing: bool = True

    @root_validator(pre=True)
    def accept_scaffold_names(cls, values: dict[str, Any]) -> dict[str, Any]:
        if "deterministic_answers" in values and "entries" not in values:
            values["entries"] = values.pop("deterministic_answers")
        return values

    def locked_entries(self) -> list[QAEntry]:
        return [e for e in self.entries if e.locked]
