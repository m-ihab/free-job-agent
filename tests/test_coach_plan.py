"""Behavioural tests for job_agent.coach.

Covers the deterministic helpers (skill normalisation, gap selection, cert /
project suggestions, weekly schedule, interview prep) and the build_coach_plan
orchestrator with the AI path disabled so the deterministic plan is exercised.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import job_agent.coach as coach
from job_agent.config import AppConfig
from job_agent.coach import (
    _deterministic_focus,
    _deterministic_steps,
    _gap_skills,
    _interview_prep,
    _normalize_skill,
    _suggested_certs,
    _suggested_projects,
    _weekly_schedule,
    build_coach_plan,
)


# --- normalisation + gap selection ---------------------------------------


def test_normalize_skill_maps_aliases_to_canonical():
    assert _normalize_skill("ml") == "Machine Learning"
    assert _normalize_skill("  PyThOn ") == "Python"
    assert _normalize_skill("power bi") == "Power BI"


def test_gap_skills_skips_blocked_and_phrase_entries():
    # Arrange: a market list mixing a real gap, a blocked buzzword, and a phrase.
    market = [
        {"name": "MLOps", "count": 9},
        {"name": "communication", "count": 8},  # blocked
        {"name": "analyser, structurer des donnees", "count": 7},  # phrase w/ comma
        {"name": "Docker", "count": 5},
    ]

    # Act: candidate only has Python, so MLOps + Docker are genuine gaps.
    gaps = _gap_skills(market, candidate_skills={"Python"})
    names = [g["name"] for g in gaps]

    # Assert: real skills kept; blocked buzzword and comma-phrase dropped.
    assert "MLOps" in names
    assert "Docker" in names
    assert "communication" not in names
    assert not any("," in n for n in names)


def test_gap_skills_hides_skill_the_candidate_already_has():
    # Arrange: candidate already lists Docker (which also implies MLOps).
    market = [{"name": "Docker", "count": 5}, {"name": "MLOps", "count": 4}]

    # Act
    gaps = _gap_skills(market, candidate_skills={"Docker"})
    names = [g["name"] for g in gaps]

    # Assert: neither Docker nor its implied MLOps is reported as a gap.
    assert "Docker" not in names
    assert "MLOps" not in names


def test_gap_skills_respects_skill_implications():
    # Arrange: candidate has PyTorch -> Deep Learning/ML implied, should be hidden.
    market = [{"name": "Deep Learning", "count": 6}, {"name": "NLP", "count": 4}]

    # Act
    gaps = _gap_skills(market, candidate_skills={"PyTorch"})
    names = [g["name"] for g in gaps]

    # Assert
    assert "Deep Learning" not in names
    assert "NLP" in names


# --- suggestion builders --------------------------------------------------


def test_suggested_certs_links_each_cert_to_its_gap():
    gaps = [{"name": "MLOps", "count": 5}]
    certs = _suggested_certs(gaps)
    assert certs
    assert all(c["because"] == "MLOps" for c in certs)
    assert len(certs) <= 4


def test_suggested_projects_caps_at_three_and_tags_gap():
    gaps = [
        {"name": "MLOps", "count": 5},
        {"name": "LLM", "count": 4},
        {"name": "Deep Learning", "count": 3},
        {"name": "NLP", "count": 2},
    ]
    projects = _suggested_projects(gaps)
    assert 1 <= len(projects) <= 3
    assert all("closes_gap" in p for p in projects)


def test_deterministic_focus_and_steps_reference_gaps():
    gaps = [{"name": "MLOps", "count": 7}, {"name": "LLM", "count": 4}]
    focus = _deterministic_focus(gaps)
    steps = _deterministic_steps(gaps)
    assert any("MLOps" in f["title"] for f in focus)
    # Steps always include the two standing actions plus per-gap project steps.
    titles = " ".join(s["title"] for s in steps)
    assert "MLOps" in titles
    assert any(s["deadline"] == "this week" for s in steps)


# --- weekly schedule ------------------------------------------------------


def test_weekly_schedule_maps_deadlines_to_dates():
    # Arrange
    steps = [
        {"title": "Ship project", "deadline": "this week"},
        {"title": "Apply to top 3", "deadline": "1 month"},
    ]
    fixed_today = date(2026, 1, 1)

    # Act
    schedule = _weekly_schedule(steps, today=fixed_today)

    # Assert: deterministic offsets (this week = +5 days, 1 month = +30 days).
    assert schedule[0]["week"] == "Week of 2026-01-06"
    assert schedule[1]["week"] == "Week of 2026-01-31"
    assert schedule[0]["title"] == "Ship project"


# --- interview prep -------------------------------------------------------


def test_interview_prep_picks_engineering_role_from_targets(sample_profile, sample_master_cv):
    # Arrange: a profile explicitly targeting data engineering.
    data = sample_profile.dict()
    data["target_roles"] = ["Data Engineer", "Data Engineering Intern"]
    profile = type(sample_profile)(**data)

    # Act
    prep = _interview_prep(profile, sample_master_cv, gaps=[{"name": "Spark", "count": 3}])

    # Assert
    assert prep["primary_role"] == "data_engineering"
    assert len(prep["questions"]) <= 10
    assert any("Spark" in q for q in prep["questions"])
    assert prep["star_scaffolds"]  # built from real experience/projects


# --- build_coach_plan (deterministic path) -------------------------------


def _make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    data_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir)


def _seed_profile_bundle(config: AppConfig) -> None:
    examples = Path(__file__).parent.parent / "examples"
    for name in ("candidate_profile.json", "master_cv.json", "master_qa_profile.json"):
        (config.profiles_dir / name).write_text(
            (examples / name).read_text(encoding="utf-8"), encoding="utf-8"
        )


def test_build_coach_plan_runs_deterministic_when_ai_unavailable(tmp_path, monkeypatch):
    # Arrange: ensure the AI branch never fires; profile bundle present.
    monkeypatch.setattr(coach, "_ai_is_available", lambda *a, **k: False)
    config = _make_config(tmp_path)
    _seed_profile_bundle(config)

    # Act
    plan = build_coach_plan(config)

    # Assert: a fully-populated deterministic plan shape.
    assert plan["source"] == "deterministic"
    assert plan["headline"]  # always filled
    assert plan["total_tracked"] == 0
    assert "schedule" in plan
    assert "interview_prep" in plan
    assert isinstance(plan["market_skills"], list)


def test_build_coach_plan_includes_gap_driven_sections_with_jobs(tmp_path, monkeypatch):
    # Arrange: seed jobs whose tech stacks are real gaps for the example profile.
    monkeypatch.setattr(coach, "_ai_is_available", lambda *a, **k: False)
    config = _make_config(tmp_path)
    _seed_profile_bundle(config)

    from job_agent.db.database import Database
    from job_agent.schemas.job import JobListing

    db = Database(config.db_path)
    db.initialize()
    for _ in range(3):
        db.save_job(JobListing(
            title="ML Engineer", company="Co",
            tech_stack=["Docker", "MLOps", "Kubernetes"], fit_score=80.0,
        ))

    # Act
    plan = build_coach_plan(config)

    # Assert: market skills aggregated from the tracked jobs, gaps surfaced.
    market_names = {m["name"] for m in plan["market_skills"]}
    assert "MLOps" in market_names or "Kubernetes" in market_names
    assert plan["total_tracked"] == 3


# --- regression: no profile bundle must not crash (WP-9) ------------------


def test_interview_prep_handles_missing_profile_and_cv():
    """_interview_prep must degrade gracefully when profile/master_cv are None
    (fresh install, no profile bundle) instead of raising AttributeError."""
    prep = _interview_prep(None, None, gaps=[{"name": "spark"}])
    assert isinstance(prep["questions"], list) and prep["questions"]
    assert any("spark" in q.lower() for q in prep["questions"])


def test_build_coach_plan_without_profile_bundle(monkeypatch, tmp_path):
    """build_coach_plan on a data dir with no profiles returns a usable plan
    (deterministic, source='deterministic') rather than crashing."""
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(tmp_path / "profiles"))
    config = AppConfig.load()
    plan = build_coach_plan(config)
    assert plan["source"] == "deterministic"
    assert isinstance(plan["headline"], str) and plan["headline"]
    assert isinstance(plan["interview_prep"]["questions"], list)
