"""Fit scoring using deterministic, local rules."""
from __future__ import annotations

from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing
from job_agent.schemas.scoring import ScoreBreakdown
from job_agent.utils import fuzzy


def _skill_overlap(job_tech: list[str], candidate_skills: list[str]) -> tuple[int, list[str], list[str]]:
    if not job_tech:
        return 50, ["No tech stack specified in job"], []
    job_lower = [t.lower() for t in job_tech]
    cand_lower = [s.lower() for s in candidate_skills]
    matched: list[str] = []
    missing: list[str] = []
    for jt in job_lower:
        if any(fuzzy.ratio(jt, cs) >= 85 or fuzzy.partial_ratio(jt, cs) >= 90 for cs in cand_lower):
            matched.append(jt)
        else:
            missing.append(jt)
    score = round(len(matched) / len(job_lower) * 100) if job_lower else 50
    notes = [f"Skill match: {len(matched)}/{len(job_lower)} ({score}%)"]
    if matched:
        notes.append(f"Matched: {', '.join(matched[:8])}")
    return min(score, 100), notes, missing


def _title_score(job_title: str, target_roles: list[str]) -> tuple[int, list[str]]:
    if not target_roles:
        return 50, ["No target roles specified"]
    scores = [(role, fuzzy.partial_ratio(role.lower(), job_title.lower())) for role in target_roles]
    role, best = max(scores, key=lambda item: item[1])
    return int(best), [f"Title match: {best}/100 vs target role '{role}'"]


def _location_score(job: JobListing, profile: CandidateProfile) -> tuple[int, list[str]]:
    if job.remote:
        if profile.remote_ok:
            return 100, ["Remote job, candidate accepts remote"]
        return 70, ["Remote job, remote preference not explicitly enabled"]
    if not profile.target_locations:
        return 50, ["No target locations specified"]
    job_loc = (job.location or "").lower()
    for loc in profile.target_locations:
        if fuzzy.partial_ratio(loc.lower(), job_loc) >= 70:
            return 100, [f"Location match: {job.location}"]
    if profile.relocation_ok:
        return 60, ["No location match, but relocation is acceptable"]
    return 20, [f"Location mismatch: {job.location or 'unknown'} not in target locations"]


def _seniority_score(job: JobListing, profile: CandidateProfile) -> tuple[int, list[str], list[str]]:
    seniority = (job.seniority or "").lower()
    title = (job.title or "").lower()
    text = f"{seniority} {title}"
    # Avoid accidentally recommending very senior roles for internship/junior profiles.
    targets = " ".join(profile.target_roles).lower()
    if any(w in targets for w in ["intern", "internship", "junior", "entry"]):
        if any(w in text for w in ["senior", "lead", "principal", "staff"]):
            return 15, ["Seniority appears higher than target roles"], ["SENIORITY_MISMATCH"]
    if seniority:
        return 80, [f"Detected seniority: {job.seniority}"], []
    return 50, ["No seniority detected"], []


def _salary_score(job: JobListing, profile: CandidateProfile) -> tuple[int, list[str], list[str]]:
    if profile.salary_min is None:
        return 50, ["No minimum salary preference set"], []
    if job.salary_max is None and job.salary_min is None:
        return 50, ["No salary posted"], []
    high = job.salary_max if job.salary_max is not None else job.salary_min
    assert high is not None
    if high < profile.salary_min:
        return 20, [f"Posted salary appears below preference: {high} < {profile.salary_min}"], ["SALARY_BELOW_PREFERENCE"]
    return 100, ["Salary appears compatible with preference"], []


def score_job(job: JobListing, profile: CandidateProfile) -> ScoreBreakdown:
    """Score a job listing against a candidate profile.

    Scores are integers from 0 to 100. This is intentionally approximate; the
    explanatory notes matter more than decimal precision.
    """
    candidate_skill_names = profile.all_skill_names()
    skill_score, skill_notes, missing = _skill_overlap(job.tech_stack, candidate_skill_names)
    title_score, title_notes = _title_score(job.title, profile.target_roles)
    loc_score, loc_notes = _location_score(job, profile)
    seniority_score, seniority_notes, seniority_risks = _seniority_score(job, profile)
    salary_score, salary_notes, salary_risks = _salary_score(job, profile)

    weights = {"skill": 0.42, "title": 0.25, "location": 0.18, "seniority": 0.10, "salary": 0.05}
    total = round(
        skill_score * weights["skill"]
        + title_score * weights["title"]
        + loc_score * weights["location"]
        + seniority_score * weights["seniority"]
        + salary_score * weights["salary"]
    )
    risk_flags = seniority_risks + salary_risks
    min_fit = getattr(profile, "min_fit_score", 70) or 70
    if total >= min_fit and not risk_flags:
        decision = "apply"
    elif total >= max(50, min_fit - 15):
        decision = "hold"
    else:
        decision = "skip"
    confidence = 0.75
    if not job.tech_stack:
        confidence -= 0.15
    if not job.location and not job.remote:
        confidence -= 0.10
    if job.company == "[To Be Parsed]" or job.title == "[To Be Parsed]":
        confidence -= 0.20
    confidence = round(max(0.1, min(0.95, confidence)), 2)
    return ScoreBreakdown(
        skill_score=skill_score,
        title_score=title_score,
        location_score=loc_score,
        seniority_score=seniority_score,
        salary_score=salary_score,
        total_score=total,
        confidence=confidence,
        decision=decision,
        notes=skill_notes + title_notes + loc_notes + seniority_notes + salary_notes,
        missing_requirements=missing,
        risk_flags=risk_flags,
    )
