"""Tests for the language and work authorization scoring additions to scorer.py."""
from __future__ import annotations


from job_agent.schemas.candidate import CandidateProfile, ContactInfo, Skill
from job_agent.schemas.job import JobListing
from job_agent.scorer import _language_score, _work_auth_score, score_job


def _profile(
    languages: list[str] | None = None,
    work_authorizations: list[str] | None = None,
    skills: list[str] | None = None,
) -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name="Test User", email="test@example.com"),
        languages=languages or [],
        work_authorizations=work_authorizations or [],
        skills=[Skill(name=s) for s in (skills or [])],
        target_roles=["Data Scientist"],
        target_locations=["Paris"],
    )


def _job(
    description: str = "",
    languages: list[str] | None = None,
    title: str = "Data Scientist",
    tech_stack: list[str] | None = None,
) -> JobListing:
    return JobListing(
        title=title,
        company="Test Co",
        description=description,
        languages=languages or [],
        tech_stack=tech_stack or [],
    )


# ── Language score ─────────────────────────────────────────────────────────

class TestLanguageScore:
    def test_no_french_requirement_returns_neutral(self) -> None:
        score, notes, risks = _language_score(
            _job(description="Data scientist role. English ok."),
            _profile(),
        )
        assert score >= 70
        assert "FRENCH_REQUIRED" not in risks

    def test_french_required_candidate_speaks_french(self) -> None:
        score, notes, risks = _language_score(
            _job(description="French required. Francais courant."),
            _profile(languages=["French", "English"]),
        )
        assert score == 100
        assert "FRENCH_REQUIRED" not in risks

    def test_french_required_candidate_no_french(self) -> None:
        score, notes, risks = _language_score(
            _job(description="French required for this role."),
            _profile(languages=["English"]),
        )
        assert score <= 20
        assert "FRENCH_REQUIRED" in risks

    def test_french_in_job_languages_list(self) -> None:
        score, notes, risks = _language_score(
            _job(languages=["french"]),
            _profile(languages=[]),
        )
        assert "FRENCH_REQUIRED" in risks

    def test_candidate_french_case_insensitive(self) -> None:
        score, notes, risks = _language_score(
            _job(description="French fluent required"),
            _profile(languages=["FRENCH"]),
        )
        assert "FRENCH_REQUIRED" not in risks
        assert score == 100


# ── Work auth score ────────────────────────────────────────────────────────

class TestWorkAuthScore:
    def test_no_restriction_returns_neutral(self) -> None:
        score, notes, risks = _work_auth_score(
            _job(description="Great data science opportunity."),
            _profile(),
        )
        assert score >= 60
        assert "SPONSORSHIP_GATED" not in risks

    def test_eu_only_candidate_has_eu_auth(self) -> None:
        score, notes, risks = _work_auth_score(
            _job(description="EU citizen required, visa sponsorship not available."),
            _profile(work_authorizations=["EU citizen"]),
        )
        assert score == 100
        assert "SPONSORSHIP_GATED" not in risks

    def test_eu_only_candidate_no_auth_listed(self) -> None:
        score, notes, risks = _work_auth_score(
            _job(description="Must be authorized to work in the EU."),
            _profile(work_authorizations=[]),
        )
        assert score <= 10
        assert "SPONSORSHIP_GATED" in risks

    def test_no_sponsorship_signal(self) -> None:
        score, notes, risks = _work_auth_score(
            _job(description="No sponsorship available."),
            _profile(work_authorizations=[]),
        )
        assert "SPONSORSHIP_GATED" in risks


# ── Full score integration ─────────────────────────────────────────────────

class TestScoreJobWithLanguageAuth:
    def test_french_required_caps_total_score(self) -> None:
        job = _job(
            description="Senior data scientist. French required.",
            tech_stack=["Python", "scikit-learn", "pandas"],
        )
        profile = _profile(
            skills=["Python", "scikit-learn", "pandas"],
            languages=["English"],  # no French
        )
        breakdown = score_job(job, profile)
        assert breakdown.total_score <= 25
        assert "FRENCH_REQUIRED" in breakdown.risk_flags
        assert breakdown.decision == "skip"

    def test_work_auth_caps_total_score(self) -> None:
        job = _job(
            description="Great role. EU citizen required, no sponsorship.",
            tech_stack=["Python"],
        )
        profile = _profile(
            skills=["Python"],
            work_authorizations=[],  # unclear
        )
        breakdown = score_job(job, profile)
        assert breakdown.total_score <= 45
        assert "SPONSORSHIP_GATED" in breakdown.risk_flags

    def test_strong_match_with_french_and_eu_auth(self) -> None:
        job = _job(
            description="Data scientist role in Paris. French required.",
            tech_stack=["Python", "pandas", "scikit-learn"],
            languages=["french"],
        )
        profile = _profile(
            skills=["Python", "pandas", "scikit-learn"],
            languages=["French", "English"],
            work_authorizations=["EU citizen"],
        )
        breakdown = score_job(job, profile)
        assert breakdown.total_score >= 70
        assert not breakdown.risk_flags
        assert breakdown.decision == "apply"
