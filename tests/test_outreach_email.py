"""Tests for the recruiter outreach email generator."""
from __future__ import annotations

import re


from job_agent.generator.outreach_email import generate_outreach_email
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, MasterCV, Skill
from job_agent.schemas.job import JobListing


def _profile(name: str = "Marie Curie", email: str = "marie@example.com") -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name=name, email=email),
        skills=[Skill(name="Python"), Skill(name="scikit-learn"), Skill(name="pandas")],
        target_roles=["Data Scientist", "ML Engineer"],
        target_locations=["Paris"],
        languages=["English", "French"],
    )


def _master_cv() -> MasterCV:
    return MasterCV(
        contact={"name": "Marie Curie", "email": "marie@example.com"},
        skills=[{"name": "Python"}, {"name": "pandas"}],
        experience=[],
        projects=[],
        education=[],
    )


def _job(recruiter: str | None = None, recruiter_email: str | None = None) -> JobListing:
    return JobListing(
        title="Data Scientist",
        company="Acme Analytics",
        location="Paris, France",
        apply_url="https://acme.jobs/data-scientist",
        tech_stack=["Python", "scikit-learn", "SQL"],
        description="We are looking for a data scientist for our Paris team.",
        recruiter_name=recruiter,
        recruiter_email=recruiter_email,
    )


class TestGenerateOutreachEmail:
    def test_contains_candidate_name(self) -> None:
        result = generate_outreach_email(_job(), _master_cv(), _profile())
        assert "Marie Curie" in result

    def test_contains_job_title(self) -> None:
        result = generate_outreach_email(_job(), _master_cv(), _profile())
        assert "Data Scientist" in result

    def test_contains_company_name(self) -> None:
        result = generate_outreach_email(_job(), _master_cv(), _profile())
        assert "Acme Analytics" in result

    def test_uses_recruiter_name_when_present(self) -> None:
        result = generate_outreach_email(_job(recruiter="Alice Morel"), _master_cv(), _profile())
        assert "Alice Morel" in result
        assert "Dear Alice Morel" in result

    def test_falls_back_to_hiring_team_when_no_recruiter(self) -> None:
        result = generate_outreach_email(_job(), _master_cv(), _profile())
        assert "Dear Hiring Team" in result

    def test_contains_subject_line(self) -> None:
        result = generate_outreach_email(_job(), _master_cv(), _profile())
        assert "Subject" in result

    def test_under_250_words(self) -> None:
        result = generate_outreach_email(_job(), _master_cv(), _profile())
        word_count = len(re.findall(r"\S+", result))
        assert word_count < 250, f"Email too long: {word_count} words"

    def test_contains_matching_skills(self) -> None:
        result = generate_outreach_email(_job(), _master_cv(), _profile())
        assert "Python" in result or "scikit-learn" in result

    def test_never_invents_email_address(self) -> None:
        result = generate_outreach_email(_job(), _master_cv(), _profile())
        # Any email in the draft should be the candidate's own email
        emails_found = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", result)
        for found_email in emails_found:
            assert found_email == "marie@example.com", f"Invented email in output: {found_email}"

    def test_contains_candidate_email_in_signature(self) -> None:
        result = generate_outreach_email(_job(), _master_cv(), _profile())
        assert "marie@example.com" in result

    def test_contains_apply_domain_in_cta(self) -> None:
        result = generate_outreach_email(_job(), _master_cv(), _profile())
        assert "acme.jobs" in result

    def test_works_when_no_recruiter_email_in_job(self) -> None:
        result = generate_outreach_email(_job(recruiter_email=None), _master_cv(), _profile())
        assert isinstance(result, str)
        assert len(result) > 50
