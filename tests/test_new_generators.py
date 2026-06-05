"""Tests for linkedin_message, interview_prep, and followup_email generators."""
from __future__ import annotations

from job_agent.generator.followup_email import generate_followup_email
from job_agent.generator.interview_prep import generate_interview_prep
from job_agent.generator.linkedin_message import (
    generate_linkedin_connect_request,
    generate_linkedin_recruiter_message,
    generate_linkedin_followup_message,
)
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, MasterCV, Skill
from job_agent.schemas.job import JobListing


def _profile() -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name="Mohamed Abdelkarim", email="m@example.com",
                            linkedin_url="https://linkedin.com/in/mo"),
        skills=[Skill(name="Python"), Skill(name="scikit-learn"), Skill(name="Transformers")],
        target_roles=["Data Scientist Intern"],
        target_locations=["Paris"],
        languages=["English", "French"],
    )


def _master_cv() -> MasterCV:
    return MasterCV(
        contact={"name": "Mohamed Abdelkarim", "email": "m@example.com"},
        skills=[{"name": "Python"}, {"name": "Transformers"}],
        experience=[{"company": "DSTI", "title": "ML Intern", "start_date": "2025-01",
                     "bullet_points": ["Built classification models", "Reduced inference time by 30%"],
                     "technologies": ["Python", "Transformers"]}],
        projects=[{"name": "AG News Classifier", "description": "NLP text classifier",
                   "technologies": ["Transformers", "DistilBERT"]}],
        education=[{"institution": "DSTI School of Engineering", "degree": "Applied MSc",
                    "field": "Data Science and AI"}],
    )


def _job() -> JobListing:
    return JobListing(
        title="Data Scientist Intern",
        company="Acme Labs",
        location="Paris",
        apply_url="https://acme.io/apply",
        tech_stack=["Python", "scikit-learn", "Transformers"],
        recruiter_name="Sophie Martin",
    )


class TestLinkedInMessage:
    def test_connect_request_under_250_chars(self) -> None:
        msg = generate_linkedin_connect_request(_job(), _master_cv(), _profile())
        assert len(msg) <= 250

    def test_connect_request_contains_role(self) -> None:
        msg = generate_linkedin_connect_request(_job(), _master_cv(), _profile())
        assert "Data Scientist" in msg or "Acme" in msg

    def test_recruiter_message_contains_company(self) -> None:
        msg = generate_linkedin_recruiter_message(_job(), _master_cv(), _profile())
        assert "Acme Labs" in msg

    def test_recruiter_message_contains_dsti(self) -> None:
        msg = generate_linkedin_recruiter_message(_job(), _master_cv(), _profile())
        assert "DSTI" in msg

    def test_recruiter_message_contains_skill(self) -> None:
        msg = generate_linkedin_recruiter_message(_job(), _master_cv(), _profile())
        assert any(s in msg for s in ["Python", "scikit-learn", "Transformers"])

    def test_followup_message_week1_references_job(self) -> None:
        msg = generate_linkedin_followup_message(_job(), _master_cv(), _profile(), days_since_apply=7)
        assert "Data Scientist" in msg or "Acme" in msg

    def test_followup_message_week2_different_text(self) -> None:
        week1 = generate_linkedin_followup_message(_job(), _master_cv(), _profile(), days_since_apply=5)
        week2 = generate_linkedin_followup_message(_job(), _master_cv(), _profile(), days_since_apply=14)
        assert week1 != week2


class TestInterviewPrep:
    def test_prep_contains_all_section_headers(self) -> None:
        prep = generate_interview_prep(_job(), _master_cv(), _profile())
        for section in ["Technical Questions", "Behavioral Questions", "Company-Specific"]:
            assert section in prep

    def test_prep_contains_company_name(self) -> None:
        prep = generate_interview_prep(_job(), _master_cv(), _profile())
        assert "Acme Labs" in prep

    def test_prep_contains_star_framework(self) -> None:
        prep = generate_interview_prep(_job(), _master_cv(), _profile())
        assert "STAR" in prep or "Situation" in prep

    def test_prep_contains_red_flags_section(self) -> None:
        prep = generate_interview_prep(_job(), _master_cv(), _profile())
        assert "Red Flags" in prep or "red flag" in prep.lower() or "Avoid" in prep

    def test_prep_non_empty(self) -> None:
        prep = generate_interview_prep(_job(), _master_cv(), _profile())
        assert len(prep.split()) > 100


class TestFollowupEmail:
    def test_week1_contains_subject(self) -> None:
        email = generate_followup_email(_job(), _master_cv(), _profile(), "week1")
        assert "Subject" in email

    def test_week1_contains_company(self) -> None:
        email = generate_followup_email(_job(), _master_cv(), _profile(), "week1")
        assert "Acme Labs" in email

    def test_week2_different_from_week1(self) -> None:
        w1 = generate_followup_email(_job(), _master_cv(), _profile(), "week1")
        w2 = generate_followup_email(_job(), _master_cv(), _profile(), "week2")
        assert w1 != w2

    def test_rejection_contains_thank_you(self) -> None:
        email = generate_followup_email(_job(), _master_cv(), _profile(), "rejection")
        assert "thank" in email.lower()

    def test_rejection_contains_door_open_sentiment(self) -> None:
        email = generate_followup_email(_job(), _master_cv(), _profile(), "rejection")
        assert "touch" in email.lower() or "future" in email.lower() or "feedback" in email.lower()

    def test_all_types_contain_candidate_name(self) -> None:
        for t in ["week1", "week2", "rejection"]:
            email = generate_followup_email(_job(), _master_cv(), _profile(), t)
            assert "Mohamed" in email
