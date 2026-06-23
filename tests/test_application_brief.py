"""Tests for the per-application headline / summary / keyword brief."""
from __future__ import annotations

from job_agent.generator.application_brief import (
    build_application_brief,
    extract_role_keywords,
    generate_headline,
    generate_summary,
)
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, MasterCV, Skill
from job_agent.schemas.job import JobListing


def _profile() -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name="Marie Curie", email="marie@example.com"),
        skills=[Skill(name="Python"), Skill(name="pandas"), Skill(name="SQL")],
        target_roles=["Data Scientist", "ML Engineer"],
        target_locations=["Paris"],
        languages=["English", "French"],
    )


def _master_cv() -> MasterCV:
    return MasterCV(contact={"name": "Marie Curie", "email": "marie@example.com"},
                    skills=[{"name": "Python"}], experience=[], projects=[], education=[])


def _job() -> JobListing:
    return JobListing(
        title="Data Scientist",
        company="Acme Analytics",
        location="Paris, France",
        tech_stack=["Python", "pandas", "SQL", "Spark", "AWS"],
        description="We need a data scientist for our Paris team.",
    )


class TestHeadline:
    def test_contains_role_and_company(self) -> None:
        headline = generate_headline(_job(), _master_cv(), _profile())
        assert "Data Scientist" in headline
        assert "Acme Analytics" in headline

    def test_features_a_matched_skill(self) -> None:
        headline = generate_headline(_job(), _master_cv(), _profile())
        assert any(skill in headline for skill in ("Python", "pandas", "SQL"))

    def test_is_single_line(self) -> None:
        assert "\n" not in generate_headline(_job(), _master_cv(), _profile())


class TestSummary:
    def test_is_non_empty_and_grounded(self) -> None:
        summary = generate_summary(_job(), _master_cv(), _profile())
        assert len(summary) > 40
        assert "Acme Analytics" in summary
        assert "Data Scientist" in summary

    def test_does_not_invent_employers(self) -> None:
        summary = generate_summary(_job(), _master_cv(), _profile())
        # Only the real company should appear; no stray "at <Other Corp>".
        assert "Google" not in summary and "Microsoft" not in summary


class TestRoleKeywords:
    def test_matched_skills_rank_first(self) -> None:
        keywords = extract_role_keywords(_job(), _profile())
        # Python/pandas/SQL (candidate has them) precede Spark/AWS (they don't).
        assert keywords.index("Python") < keywords.index("Spark")
        assert keywords.index("SQL") < keywords.index("AWS")

    def test_respects_limit_and_dedupes(self) -> None:
        job = _job()
        job.tech_stack = ["Python", "Python", "pandas", "SQL", "Spark", "AWS", "Docker", "Kubernetes"]
        keywords = extract_role_keywords(job, _profile(), limit=4)
        assert len(keywords) == 4
        assert len(keywords) == len({k.lower() for k in keywords})

    def test_empty_tech_stack_returns_empty(self) -> None:
        job = _job()
        job.tech_stack = []
        assert extract_role_keywords(job, _profile()) == []


class TestBuildApplicationBrief:
    def test_returns_all_three_parts(self) -> None:
        brief = build_application_brief(_job(), _master_cv(), _profile())
        assert set(brief) == {"headline", "summary", "keywords"}
        assert isinstance(brief["keywords"], list)
        assert brief["headline"] and brief["summary"]
