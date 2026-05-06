"""Candidate profile schemas."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class ContactInfo(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    email: str
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    work_authorization: Optional[str] = None


class Education(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    institution: str
    degree: str
    field: str
    start_year: int
    end_year: Optional[int] = None
    gpa: Optional[float] = None
    honors: list[str] = []


class WorkExperience(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    company: str
    title: str
    start_date: str
    end_date: Optional[str] = None
    location: Optional[str] = None
    bullet_points: list[str] = []
    technologies: list[str] = []


class Project(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    description: str
    url: Optional[str] = None
    technologies: list[str] = []


class Certification(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    issuer: str
    year: int
    url: Optional[str] = None


class Skill(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    category: str
    years_experience: Optional[float] = None


class CandidateProfile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contact: ContactInfo
    summary: str = ""
    skills: list[Skill] = []
    languages: list[str] = []
    work_authorizations: list[str] = []
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    target_roles: list[str] = []
    target_locations: list[str] = []
    remote_ok: bool = True
    relocation_ok: bool = False


class CVSection(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str
    content: list[str] = []


class MasterCV(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contact: ContactInfo
    summary: str = ""
    education: list[Education] = []
    experience: list[WorkExperience] = []
    projects: list[Project] = []
    certifications: list[Certification] = []
    skills: list[Skill] = []


class QAEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question_pattern: str
    answer: str
    locked: bool = True


class QAProfile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    entries: list[QAEntry] = []
