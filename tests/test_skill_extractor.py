"""Tests for implicit skill extraction and job keyword gap mining."""
from __future__ import annotations

from job_agent.schemas.candidate import (
    CandidateProfile,
    ContactInfo,
    MasterCV,
    Project,
    Skill,
)
from job_agent.schemas.job import JobListing
from job_agent.skill_extractor import (
    extract_implied_skills,
    mine_job_keywords,
    suggest_trend_gaps,
)


def _profile(skill_names: list[str]) -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name="Test", email="t@example.com"),
        skills=[Skill(name=n) for n in skill_names],
    )


def _master_cv(projects: list[Project] | None = None) -> MasterCV:
    return MasterCV(
        contact=ContactInfo(name="Test", email="t@example.com"),
        projects=projects or [],
    )


def _job(**overrides) -> JobListing:
    base = dict(title="Data Scientist", company="ACME")
    base.update(overrides)
    return JobListing(**base)


# --- extract_implied_skills ----------------------------------------------

def test_implied_skills_derived_from_existing_skill():
    implied = extract_implied_skills(_profile(["pytorch"]), _master_cv())
    names = {s.name for s in implied}

    assert "Deep Learning" in names
    assert all(s.implied_by == "pytorch" for s in implied)


def test_implied_skills_exclude_already_listed():
    profile = _profile(["pytorch", "Deep Learning"])
    names = {s.name for s in extract_implied_skills(profile, _master_cv())}

    assert "Deep Learning" not in names  # already on the profile
    assert "Neural Networks" in names


def test_implied_skills_deduplicated_across_sources():
    # pytorch and tensorflow both imply "Neural Networks" — should appear once.
    implied = extract_implied_skills(_profile(["pytorch", "tensorflow"]), _master_cv())
    names = [s.name for s in implied]

    assert names.count("Neural Networks") == 1


def test_implied_skills_mined_from_project_technologies():
    cv = _master_cv([Project(name="P", description="d", technologies=["docker"])])
    names = {s.name for s in extract_implied_skills(_profile([]), cv)}

    assert "Containerisation" in names


# --- mine_job_keywords ----------------------------------------------------

def test_mine_job_keywords_empty_for_no_jobs():
    assert mine_job_keywords([], _profile(["python"])) == []


def test_mine_job_keywords_respects_min_frequency():
    jobs = [
        _job(tech_stack=["airflow"]),
        _job(tech_stack=["airflow"], company="B"),
        _job(tech_stack=["spark"], company="C"),  # appears once -> below min_frequency
    ]

    gaps = mine_job_keywords(jobs, _profile([]), min_frequency=2)
    skills = {g.skill for g in gaps}

    assert "airflow" in skills
    assert "spark" not in skills


def test_mine_job_keywords_excludes_skills_already_on_profile():
    jobs = [_job(tech_stack=["python"]), _job(tech_stack=["python"], company="B")]

    gaps = mine_job_keywords(jobs, _profile(["Python"]), min_frequency=1)

    assert all(g.skill.lower() != "python" for g in gaps)


def test_mine_job_keywords_dedupes_within_single_job():
    jobs = [_job(tech_stack=["airflow", "airflow"])]

    gaps = mine_job_keywords(jobs, _profile([]), min_frequency=1)
    airflow = next(g for g in gaps if g.skill == "airflow")

    assert airflow.frequency == 1  # counted once per job, not per mention


# --- suggest_trend_gaps ---------------------------------------------------

def test_suggest_trend_gaps_excludes_owned_skills_case_insensitively():
    gaps = suggest_trend_gaps(_profile(["llm", "docker"]))

    assert "LLM" not in gaps
    assert "Docker" not in gaps
    assert "RAG" in gaps
