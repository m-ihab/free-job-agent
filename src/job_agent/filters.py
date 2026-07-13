"""Hard filters that eliminate or hold jobs before packet generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing
from job_agent.utils import fuzzy
from job_agent.work_auth import WorkAuthClass, classify_work_auth


@dataclass
class FilterConfig:
    blocked_companies: list[str] = field(default_factory=list)
    blocked_keywords: list[str] = field(default_factory=list)
    required_keywords: list[str] = field(default_factory=list)
    min_salary: Optional[int] = None
    max_salary: Optional[int] = None
    remote_only: bool = False
    allowed_locations: list[str] = field(default_factory=list)
    disallowed_job_types: list[str] = field(default_factory=list)
    max_seniority: Optional[str] = None
    fuzzy_threshold: int = 80
    hide_sponsorship_gated: bool = False


@dataclass
class FilterResult:
    passed: bool
    decision: str = "pass"  # pass, reject, hold
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)


def _text(job: JobListing) -> str:
    return f"{job.title} {job.company} {job.location or ''} {job.description} {' '.join(job.requirements)} {' '.join(job.tech_stack)}".lower()


def apply_filters(
    job: JobListing,
    config: FilterConfig,
    profile: Optional[CandidateProfile] = None,
) -> FilterResult:
    """Apply all hard filters and return pass/fail with reasons.

    A failed hard filter should block packet generation unless the user passes
    an explicit --force flag from the CLI.
    """
    reasons: list[str] = []
    reason_codes: list[str] = []
    risk_flags: list[str] = []
    text = _text(job)

    def reject(rule: str, message: str) -> None:
        reason_codes.append(rule)
        reasons.append(message)

    blocked_companies = list(config.blocked_companies)
    if profile:
        blocked_companies.extend(profile.excluded_companies)
    for company in blocked_companies:
        if fuzzy.partial_ratio(company.lower(), job.company.lower()) >= config.fuzzy_threshold:
            reject("blocked_company", f"Blocked company: {company}")

    for kw in config.blocked_keywords:
        if kw.lower() in text:
            reject("blocked_keyword", f"Blocked keyword: {kw}")

    for kw in config.required_keywords:
        if kw.lower() not in text:
            reject("missing_required_keyword", f"Missing required keyword: {kw}")

    min_salary = config.min_salary
    if min_salary is None and profile and profile.salary_min:
        min_salary = profile.salary_min
    if min_salary and job.salary_max is not None and job.salary_max < min_salary:
        reject("salary_too_low", f"Salary too low: {job.salary_max} < {min_salary}")

    if config.remote_only and not job.remote:
        reject("not_remote", "Job is not remote")

    allowed_locations = config.allowed_locations or (profile.target_locations if profile else [])
    remote_ok = profile.remote_ok if profile else False
    relocation_ok = profile.relocation_ok if profile else False
    if allowed_locations and not job.remote:
        job_location = (job.location or "").lower()
        loc_match = any(
            fuzzy.partial_ratio(loc.lower(), job_location) >= config.fuzzy_threshold
            for loc in allowed_locations
        )
        if not job.location:
            risk_flags.append("LOCATION_UNKNOWN")
        elif not loc_match and not relocation_ok:
            reject("location_not_allowed", f"Location not allowed: {job.location or 'unknown'}")
    elif not job.remote and profile and not remote_ok and not relocation_ok and not profile.target_locations:
        risk_flags.append("NO_LOCATION_PREFERENCES")

    if config.disallowed_job_types and job.job_type:
        if job.job_type.lower() in [t.lower() for t in config.disallowed_job_types]:
            reject("job_type_not_allowed", f"Job type not allowed: {job.job_type}")

    if profile:
        auth_keywords = ["sponsorship", "visa", "work authorization", "authorized to work"]
        if any(kw in text for kw in auth_keywords) and not profile.work_authorizations:
            risk_flags.append("WORK_AUTHORIZATION_MENTIONED_NO_PROFILE_ANSWER")
        auth = classify_work_auth(job, profile)
        if auth.work_auth_class == WorkAuthClass.SPONSORSHIP_GATED:
            risk_flags.append("SPONSORSHIP_GATED")
            if config.hide_sponsorship_gated:
                reject("sponsorship_gated", auth.rationale)

    decision = "pass" if not reasons else "reject"
    if risk_flags and not reasons:
        decision = "hold"
    return FilterResult(
        passed=len(reasons) == 0,
        decision=decision,
        reasons=reasons,
        risk_flags=risk_flags,
        reason_codes=reason_codes,
    )
