"""Hypothetical profile changes used only for labeled gap-score simulations."""
from __future__ import annotations

from dataclasses import dataclass

from job_agent.schemas.candidate import CandidateProfile, Skill
from job_agent.schemas.job import JobListing
from job_agent.scorer import score_job


@dataclass(frozen=True)
class SimulatedJobLift:
    job_id: str
    before_score: int
    after_score: int
    lift: int


@dataclass(frozen=True)
class SimulatedScoreLift:
    label: str
    average_points: float
    per_job: list[SimulatedJobLift]


def simulate_score_lift(
    name: str,
    skills: set[str],
    jobs: list[JobListing],
    profile: CandidateProfile,
) -> SimulatedScoreLift:
    """Re-run the production scorer with one cluster hypothetically closed."""
    rows: list[SimulatedJobLift] = []
    for job in sorted(jobs, key=lambda item: item.id):
        before = score_job(job, profile).total_score
        simulated = _close_gap(profile, name, skills, job)
        after = score_job(job, simulated).total_score
        rows.append(SimulatedJobLift(job.id, before, after, after - before))
    average = round(sum(row.lift for row in rows) / len(rows), 2) if rows else 0.0
    return SimulatedScoreLift("simulated", average, rows)


def _close_gap(
    profile: CandidateProfile,
    name: str,
    skills: set[str],
    job: JobListing,
) -> CandidateProfile:
    simulated = profile.copy(deep=True)
    known = {skill.name.casefold() for skill in simulated.skills}
    for skill in sorted(skills, key=str.casefold):
        if skill.casefold() not in known:
            simulated.skills.append(Skill(name=skill, category="simulated_gap"))
    if name == "FRENCH_REQUIRED" and not any("french" in lang.casefold() for lang in simulated.languages):
        simulated.languages.append("French")
    elif name == "SPONSORSHIP_GATED":
        simulated.work_authorizations.append("EU citizen")
        simulated.needs_sponsorship_for_cdi = False
    elif name == "SENIORITY_MISMATCH":
        simulated.target_roles = [job.title]
    elif name == "SALARY_BELOW_PREFERENCE":
        simulated.salary_min = None
    return simulated
