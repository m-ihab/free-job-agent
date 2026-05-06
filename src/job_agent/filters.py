"""Hard filters that eliminate jobs before LLM processing."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz

from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing


@dataclass
class FilterConfig:
    """Configuration for hard filters."""
    blocked_companies: list[str] = field(default_factory=list)
    blocked_keywords: list[str] = field(default_factory=list)
    required_keywords: list[str] = field(default_factory=list)
    min_salary: Optional[int] = None
    max_salary: Optional[int] = None
    remote_only: bool = False
    allowed_locations: list[str] = field(default_factory=list)
    disallowed_job_types: list[str] = field(default_factory=list)
    fuzzy_threshold: int = 80


@dataclass
class FilterResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def apply_filters(
    job: JobListing,
    config: FilterConfig,
    profile: Optional[CandidateProfile] = None,
) -> FilterResult:
    """Apply all hard filters and return pass/fail with reasons."""
    reasons: list[str] = []
    text = f"{job.title} {job.company} {job.description} {' '.join(job.requirements)}".lower()

    for company in config.blocked_companies:
        if fuzz.partial_ratio(company.lower(), job.company.lower()) >= config.fuzzy_threshold:
            reasons.append(f"Blocked company: {company}")

    for kw in config.blocked_keywords:
        if kw.lower() in text:
            reasons.append(f"Blocked keyword: {kw}")

    for kw in config.required_keywords:
        if kw.lower() not in text:
            reasons.append(f"Missing required keyword: {kw}")

    if config.min_salary and job.salary_max is not None:
        if job.salary_max < config.min_salary:
            reasons.append(f"Salary too low: {job.salary_max} < {config.min_salary}")

    if config.remote_only and not job.remote:
        reasons.append("Job is not remote")

    if config.allowed_locations and not job.remote:
        job_location = (job.location or "").lower()
        loc_match = any(
            fuzz.partial_ratio(loc.lower(), job_location) >= config.fuzzy_threshold
            for loc in config.allowed_locations
        )
        if not loc_match:
            reasons.append(f"Location not in allowed list: {job.location}")

    if config.disallowed_job_types and job.job_type:
        if job.job_type.lower() in [t.lower() for t in config.disallowed_job_types]:
            reasons.append(f"Job type not allowed: {job.job_type}")

    if profile:
        auth_keywords = ["sponsorship", "visa", "work authorization", "authorized to work"]
        for kw in auth_keywords:
            if kw in text:
                if not profile.work_authorizations:
                    reasons.append(f"Job may require work authorization: {kw} mentioned")
                break

    return FilterResult(passed=len(reasons) == 0, reasons=reasons)
