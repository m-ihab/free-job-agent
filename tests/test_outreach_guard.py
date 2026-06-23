"""Tests for the outreach honesty guard.

The guard exists to enforce the hard project rule: an LLM-enhanced outreach
message must never introduce candidate facts (metrics, years of experience,
visa/credential claims) that are absent from the source draft, profile, or job.
The guard is conservative — when in doubt it flags, and callers fall back to the
deterministic draft.
"""
from __future__ import annotations

from job_agent.generator.outreach_guard import assert_grounded
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, MasterCV, Skill
from job_agent.schemas.job import JobListing


def _profile() -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name="Marie Curie", email="marie@example.com"),
        skills=[Skill(name="Python"), Skill(name="pandas")],
        target_roles=["Data Scientist"],
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
        tech_stack=["Python", "SQL"],
        description="We need a data scientist for our Paris team.",
    )


_DRAFT = "Hi! I came across Acme Analytics' Data Scientist role and I'd love to connect."


class TestAssertGrounded:
    def test_unchanged_draft_is_grounded(self) -> None:
        ok, violations = assert_grounded(_DRAFT, draft=_DRAFT, job=_job(),
                                         master_cv=_master_cv(), profile=_profile())
        assert ok is True
        assert violations == []

    def test_rephrasing_with_known_facts_is_grounded(self) -> None:
        enhanced = ("Hi! I noticed the Data Scientist opening at Acme Analytics in Paris. "
                    "My Python and pandas background fits it well — I'd love to connect.")
        ok, violations = assert_grounded(enhanced, draft=_DRAFT, job=_job(),
                                         master_cv=_master_cv(), profile=_profile())
        assert ok is True, violations

    def test_invented_years_of_experience_is_flagged(self) -> None:
        enhanced = _DRAFT + " I bring 7 years of production machine-learning experience."
        ok, violations = assert_grounded(enhanced, draft=_DRAFT, job=_job(),
                                         master_cv=_master_cv(), profile=_profile())
        assert ok is False
        assert any("7" in v for v in violations)

    def test_invented_metric_percentage_is_flagged(self) -> None:
        enhanced = _DRAFT + " I improved model accuracy by 30% at my last role."
        ok, violations = assert_grounded(enhanced, draft=_DRAFT, job=_job(),
                                         master_cv=_master_cv(), profile=_profile())
        assert ok is False
        assert any("30" in v for v in violations)

    def test_invented_visa_claim_is_flagged(self) -> None:
        enhanced = _DRAFT + " I already hold EU work authorization and need no sponsorship."
        ok, violations = assert_grounded(enhanced, draft=_DRAFT, job=_job(),
                                         master_cv=_master_cv(), profile=_profile())
        assert ok is False
        assert any("sponsor" in v.lower() or "visa" in v.lower() or "authorization" in v.lower()
                   for v in violations)

    def test_number_present_in_source_is_allowed(self) -> None:
        # The draft itself mentions a 6-month stage; keeping it is fine.
        draft = _DRAFT + " I'm seeking a 6-month stage."
        enhanced = "I'd love a 6-month stage with Acme Analytics as a Data Scientist."
        ok, violations = assert_grounded(enhanced, draft=draft, job=_job(),
                                         master_cv=_master_cv(), profile=_profile())
        assert ok is True, violations
