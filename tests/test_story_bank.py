"""Tests for the persistent STAR interview story bank."""
from __future__ import annotations

from pathlib import Path

import pytest

from job_agent import story_bank
from job_agent.db.database import Database
from job_agent.schemas.candidate import ContactInfo, MasterCV, Project, WorkExperience
from job_agent.schemas.job import JobListing


def _master_cv() -> MasterCV:
    return MasterCV(
        contact=ContactInfo(name="Test Candidate", email="test@example.com"),
        experience=[
            WorkExperience(
                company="DataCorp",
                title="Data Analyst",
                start_date="2023-01",
                end_date="2024-06",
                bullet_points=[
                    "Built churn prediction pipeline in Python reducing manual reporting",
                    "Automated weekly SQL dashboards for the sales team",
                ],
                technologies=["python", "sql", "airflow"],
            )
        ],
        projects=[
            Project(
                name="Fraud Detector",
                description="Real-time fraud detection with gradient boosting",
                technologies=["python", "xgboost"],
                bullet_points=["Deployed model as a REST API with FastAPI"],
            )
        ],
    )


def _job(**kwargs) -> JobListing:
    base: dict = dict(
        title="Machine Learning Engineer",
        company="Acme",
        description="ML engineering role",
        tech_stack=["python", "xgboost"],
        requirements=["Experience deploying ML models"],
        missing_requirements=["Kubernetes"],
    )
    base.update(kwargs)
    return JobListing(**base)


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


# ---- seeding from master CV (grounded, no invention) ----

def test_seed_stories_from_cv_covers_experience_and_projects() -> None:
    stories = story_bank.seed_stories_from_cv(_master_cv())
    titles = [s.title for s in stories]
    assert any("DataCorp" in t for t in titles)
    assert any("Fraud Detector" in t for t in titles)


def test_seed_stories_only_use_cv_text() -> None:
    cv = _master_cv()
    cv_text = " ".join([
        *(b for e in cv.experience for b in e.bullet_points),
        *(p.description for p in cv.projects),
        *(b for p in cv.projects for b in p.bullet_points),
        *(f"{e.title} {e.company}" for e in cv.experience),
        *(p.name for p in cv.projects),
    ]).lower()
    for story in story_bank.seed_stories_from_cv(cv):
        for fragment in [story.situation, story.action, story.result]:
            for sentence in filter(None, (part.strip() for part in fragment.split("\n"))):
                assert sentence.lower().lstrip("- ") in cv_text or sentence.lower() in cv_text.replace("\n", " ")


def test_sync_story_bank_is_idempotent(db: Database) -> None:
    cv = _master_cv()
    added_first = story_bank.sync_story_bank(db, cv)
    added_second = story_bank.sync_story_bank(db, cv)
    assert added_first > 0
    assert added_second == 0
    assert len(db.list_stories()) == added_first


def test_sync_preserves_user_edits(db: Database) -> None:
    cv = _master_cv()
    story_bank.sync_story_bank(db, cv)
    stories = db.list_stories()
    edited = dict(stories[0])
    edited["result"] = "Cut churn by a lot (my own edit)"
    db.save_story(edited)
    story_bank.sync_story_bank(db, cv)
    reloaded = db.get_story(edited["id"])
    assert reloaded is not None
    assert reloaded["result"] == "Cut churn by a lot (my own edit)"


# ---- DB roundtrip ----

def test_story_save_list_delete_roundtrip(db: Database) -> None:
    db.save_story({
        "id": "story_test1",
        "title": "Manual story",
        "skills": ["python"],
        "situation": "S",
        "task": "T",
        "action": "A",
        "result": "R",
        "reflection": "",
        "source": "manual",
    })
    rows = db.list_stories()
    assert len(rows) == 1
    assert rows[0]["skills"] == ["python"]
    db.delete_story("story_test1")
    assert db.list_stories() == []


# ---- relevance ranking ----

def test_relevant_stories_ranks_matching_skills_first() -> None:
    stories = story_bank.seed_stories_from_cv(_master_cv())
    ranked = story_bank.relevant_stories(_job(tech_stack=["xgboost"]), stories, limit=2)
    assert ranked
    assert "Fraud Detector" in ranked[0].title


def test_relevant_stories_respects_limit() -> None:
    stories = story_bank.seed_stories_from_cv(_master_cv())
    assert len(story_bank.relevant_stories(_job(), stories, limit=1)) == 1


# ---- markdown rendering ----

def test_render_story_bank_markdown_has_star_and_gap_warnings() -> None:
    stories = story_bank.seed_stories_from_cv(_master_cv())
    markdown = story_bank.render_story_bank_markdown(_job(), stories, ["Kubernetes"])
    assert "Situation" in markdown
    assert "Action" in markdown
    assert "Kubernetes" in markdown
    assert "do not claim" in markdown.lower()


def test_render_story_bank_markdown_empty_stories_is_graceful() -> None:
    markdown = story_bank.render_story_bank_markdown(_job(), [], [])
    assert "story bank" in markdown.lower()
