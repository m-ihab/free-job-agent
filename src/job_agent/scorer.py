"""Fit scoring using deterministic rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz

from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing


@dataclass
class ScoreBreakdown:
    """Detailed scoring breakdown."""
    skill_score: float = 0.0
    title_score: float = 0.0
    location_score: float = 0.0
    experience_score: float = 0.0
    total_score: float = 0.0
    notes: list[str] = field(default_factory=list)


def _skill_overlap(
    job_tech: list[str], candidate_skills: list[str]
) -> tuple[float, list[str]]:
    if not job_tech:
        return 0.5, ["No tech stack specified in job"]

    job_lower = [t.lower() for t in job_tech]
    cand_lower = [s.lower() for s in candidate_skills]

    matched = []
    for jt in job_lower:
        for cs in cand_lower:
            if fuzz.ratio(jt, cs) >= 85:
                matched.append(jt)
                break

    score = len(matched) / len(job_lower) if job_lower else 0.5
    notes = [f"Skill match: {len(matched)}/{len(job_lower)} ({score:.0%})"]
    if matched:
        notes.append(f"Matched: {', '.join(matched[:5])}")
    return min(score, 1.0), notes


def _title_score(job_title: str, target_roles: list[str]) -> tuple[float, list[str]]:
    if not target_roles:
        return 0.5, ["No target roles specified"]

    best = max(
        fuzz.partial_ratio(role.lower(), job_title.lower()) for role in target_roles
    )
    score = best / 100.0
    return score, [f"Title match score: {best}/100 for '{job_title}'"]


def _location_score(
    job: JobListing, profile: CandidateProfile
) -> tuple[float, list[str]]:
    if job.remote:
        if profile.remote_ok:
            return 1.0, ["Remote job, candidate accepts remote"]
        else:
            return 0.7, ["Remote job, candidate preference not set for remote"]

    if profile.remote_ok and not profile.target_locations:
        return 0.8, ["Candidate is remote-ok"]

    if not profile.target_locations:
        return 0.5, ["No target locations specified"]

    job_loc = (job.location or "").lower()
    for loc in profile.target_locations:
        if fuzz.partial_ratio(loc.lower(), job_loc) >= 70:
            return 1.0, [f"Location match: {job.location}"]

    if profile.relocation_ok:
        return 0.6, ["No location match but relocation is ok"]

    return 0.2, [f"Location mismatch: {job.location} not in target locations"]


def score_job(job: JobListing, profile: CandidateProfile) -> ScoreBreakdown:
    """Score a job listing against a candidate profile using deterministic rules."""
    candidate_skill_names = [s.name for s in profile.skills]

    skill_score, skill_notes = _skill_overlap(job.tech_stack, candidate_skill_names)
    title_score, title_notes = _title_score(job.title, profile.target_roles)
    loc_score, loc_notes = _location_score(job, profile)

    weights = {"skill": 0.5, "title": 0.3, "location": 0.2}
    total = (
        skill_score * weights["skill"]
        + title_score * weights["title"]
        + loc_score * weights["location"]
    )

    return ScoreBreakdown(
        skill_score=round(skill_score, 3),
        title_score=round(title_score, 3),
        location_score=round(loc_score, 3),
        total_score=round(total, 3),
        notes=skill_notes + title_notes + loc_notes,
    )
