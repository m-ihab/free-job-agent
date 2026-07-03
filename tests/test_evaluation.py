"""Tests for the career-ops-style A-F evaluation rubric."""
from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.db.database import Database
from job_agent.generator.evaluation import (
    Evaluation,
    evaluate_job,
    grade_for_score,
    salary_comparables,
)
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, Skill
from job_agent.schemas.job import JobListing


def _job(**kwargs) -> JobListing:
    base: dict = dict(
        title="Data Scientist",
        company="Acme",
        location="Paris",
        description="Machine learning role with Python and SQL. English-speaking team.",
        tech_stack=["python", "sql"],
        languages=["English"],
    )
    base.update(kwargs)
    return JobListing(**base)


def _profile(**kwargs) -> CandidateProfile:
    base: dict = dict(
        contact=ContactInfo(name="Test Candidate", email="test@example.com"),
        skills=[Skill(name="Python"), Skill(name="SQL")],
        target_roles=["Data Scientist"],
        target_locations=["Paris"],
        languages=["English", "French"],
        can_do_stage=True,
    )
    base.update(kwargs)
    return CandidateProfile(**base)


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


# ---- grade boundaries ----

def test_grade_boundaries() -> None:
    assert grade_for_score(100) == "A"
    assert grade_for_score(85) == "A"
    assert grade_for_score(84) == "B"
    assert grade_for_score(70) == "B"
    assert grade_for_score(69) == "C"
    assert grade_for_score(55) == "C"
    assert grade_for_score(54) == "D"
    assert grade_for_score(40) == "D"
    assert grade_for_score(39) == "F"
    assert grade_for_score(0) == "F"


# ---- evaluation composition ----

def test_evaluate_job_returns_dimensions_and_overall() -> None:
    evaluation = evaluate_job(_job(), _profile())
    assert isinstance(evaluation, Evaluation)
    names = [d.name for d in evaluation.dimensions]
    for expected in ["skills", "title", "location", "seniority", "language", "salary",
                     "work_authorization", "freshness"]:
        assert expected in names
    assert 0 <= evaluation.overall_score <= 100
    assert evaluation.overall_grade in {"A", "B", "C", "D", "F"}
    assert evaluation.recommendation


def test_evaluate_job_is_deterministic() -> None:
    job, profile = _job(), _profile()
    first = evaluate_job(job, profile)
    second = evaluate_job(job, profile)
    assert first.overall_score == second.overall_score
    assert [d.grade for d in first.dimensions] == [d.grade for d in second.dimensions]


def test_semantic_dimension_excluded_when_unavailable() -> None:
    evaluation = evaluate_job(_job(), _profile())
    assert "semantic" not in [d.name for d in evaluation.dimensions]


def test_semantic_dimension_included_when_provided() -> None:
    evaluation = evaluate_job(_job(), _profile(), semantic_score=88)
    semantic = [d for d in evaluation.dimensions if d.name == "semantic"]
    assert len(semantic) == 1
    assert semantic[0].score == 88


def test_weights_renormalize_to_one() -> None:
    evaluation = evaluate_job(_job(), _profile())
    assert sum(d.weight for d in evaluation.dimensions) == pytest.approx(1.0)
    with_semantic = evaluate_job(_job(), _profile(), semantic_score=90)
    assert sum(d.weight for d in with_semantic.dimensions) == pytest.approx(1.0)


def test_french_required_caps_overall() -> None:
    job = _job(description="French required for this role, niveau c1 obligatoire.")
    profile = _profile(languages=["English"])
    evaluation = evaluate_job(job, profile)
    assert evaluation.overall_score <= 25
    assert evaluation.overall_grade == "F"


def test_high_fit_job_grades_well() -> None:
    evaluation = evaluate_job(_job(), _profile())
    assert evaluation.overall_grade in {"A", "B"}


# ---- markdown / dict output ----

def test_to_markdown_contains_grades_and_dimensions() -> None:
    evaluation = evaluate_job(_job(), _profile())
    markdown = evaluation.to_markdown()
    assert "Overall" in markdown
    assert evaluation.overall_grade in markdown
    assert "skills" in markdown.lower()


def test_to_dict_roundtrips_key_fields() -> None:
    evaluation = evaluate_job(_job(), _profile())
    data = evaluation.to_dict()
    assert data["overall_grade"] == evaluation.overall_grade
    assert data["overall_score"] == evaluation.overall_score
    assert len(data["dimensions"]) == len(evaluation.dimensions)


# ---- salary comparables ----

def test_salary_comparables_with_local_evidence(db: Database) -> None:
    db.save_job(_job(id="a", title="Data Scientist", salary_min=40000, salary_max=50000))
    db.save_job(_job(id="b", title="Senior Data Scientist", salary_min=60000, salary_max=70000))
    db.save_job(_job(id="c", title="Boulanger", salary_min=20000, salary_max=22000))
    lines = salary_comparables(db, _job(title="Data Scientist"))
    joined = "\n".join(lines)
    assert "2" in joined  # two comparable data roles
    assert "45" in joined or "45000" in joined or "65" in joined or "median" in joined.lower()


def test_salary_comparables_without_evidence(db: Database) -> None:
    lines = salary_comparables(db, _job())
    assert any("no local salary evidence" in line.lower() for line in lines)
