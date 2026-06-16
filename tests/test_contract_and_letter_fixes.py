"""RED tests — contract detection, cover letter, and CSS modal fixes.

Run with: pytest tests/test_contract_and_letter_fixes.py -v
All tests here are expected to FAIL before the fixes are applied.
"""
from __future__ import annotations

import pytest

from job_agent.renderer.latex_render import _detect_contract_family, _tailored_summary
from job_agent.generator.cover_letter import generate_cover_letter, _adjust_summary_for_contract
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, MasterCV, Skill
from job_agent.schemas.job import JobListing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _job(title: str, job_type: str = "", description: str = "") -> JobListing:
    return JobListing(
        title=title,
        company="Acme Corp",
        job_type=job_type,
        description=description,
    )


def _stage_job() -> JobListing:
    return JobListing(
        title="Stage Data Scientist",
        company="Acme Corp",
        job_type="stage",
        description="6-month internship for a data science student.",
    )


def _cdi_job() -> JobListing:
    return JobListing(
        title="Senior Data Scientist",
        company="Acme Corp",
        job_type="CDI",
        description="Permanent full-time role in our Paris team.",
    )


def _junior_cdi_job() -> JobListing:
    return JobListing(
        title="Junior Data Scientist",
        company="Acme Corp",
        job_type="CDI",
        description="Entry-level permanent position. No French required.",
    )


def _graduate_job() -> JobListing:
    return JobListing(
        title="Graduate Data Engineer",
        company="Acme Corp",
        job_type="",
        description="Graduate-level permanent role based in London.",
    )


def _profile() -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name="Mohamed Ihab", email="m@example.com"),
        skills=[Skill(name="Python"), Skill(name="Machine Learning")],
        languages=["English"],
        summary="I am a data science master's student. Available for a 6 month Data Science internship.",
    )


def _master_cv() -> MasterCV:
    return MasterCV(
        contact={"name": "Mohamed Ihab", "email": "m@example.com"},
        summary="I am a data science master's student. Available for a 6 month Data Science internship.",
        skills=[{"name": "Python"}],
        experience=[],
        projects=[],
    )


# ---------------------------------------------------------------------------
# Phase 1A: _detect_contract_family should NOT classify junior/graduate as stage
# ---------------------------------------------------------------------------

class TestContractDetection:
    def test_stage_job_detected_as_stage(self) -> None:
        assert _detect_contract_family(_stage_job()) == "stage"

    def test_cdi_job_detected_as_cdi(self) -> None:
        assert _detect_contract_family(_cdi_job()) == "cdi"

    def test_junior_cdi_NOT_stage(self) -> None:
        """'Junior' in the title should NOT classify the job as a stage/internship."""
        result = _detect_contract_family(_junior_cdi_job())
        assert result != "stage", (
            f"'Junior' in CDI job title incorrectly classified as stage: got '{result}'. "
            "Remove 'junior' from _STAGE_TERMS_RE."
        )

    def test_graduate_role_NOT_stage(self) -> None:
        """'Graduate' in a permanent role should NOT classify it as a stage."""
        result = _detect_contract_family(_graduate_job())
        assert result != "stage", (
            f"'Graduate' in permanent job title incorrectly classified as stage: got '{result}'. "
            "Remove 'graduate' from _STAGE_TERMS_RE."
        )

    def test_alternance_beats_stage_keywords(self) -> None:
        job = JobListing(
            title="Alternance Data Scientist intern",
            company="X",
            description="alternance role mixing stage and alternance terms",
        )
        assert _detect_contract_family(job) == "alternance"

    def test_role_fallback_for_generic_title(self) -> None:
        job = JobListing(title="Data Scientist", company="X")
        assert _detect_contract_family(job) == "role"


# ---------------------------------------------------------------------------
# Phase 1B: Cover letter must not say "internship" for junior / CDI roles
# ---------------------------------------------------------------------------

class TestCoverLetterContractPhrasing:
    def test_stage_letter_can_mention_internship(self) -> None:
        letter = generate_cover_letter(_stage_job(), _master_cv(), _profile())
        # For a real stage it is OK to keep the internship phrasing
        # (we just check it doesn't crash and has content)
        assert len(letter) > 100

    def test_cdi_letter_does_not_say_internship(self) -> None:
        letter = generate_cover_letter(_cdi_job(), _master_cv(), _profile())
        assert "internship" not in letter.lower(), (
            "Cover letter for a CDI role still contains 'internship'. "
            "Fix _adjust_summary_for_contract or _detect_contract_family."
        )

    def test_junior_cdi_letter_does_not_say_internship(self) -> None:
        letter = generate_cover_letter(_junior_cdi_job(), _master_cv(), _profile())
        assert "internship" not in letter.lower(), (
            "Cover letter for a Junior CDI role says 'internship'. "
            "Root cause: 'junior' in _STAGE_TERMS_RE makes it look like a stage."
        )

    def test_graduate_letter_does_not_say_internship(self) -> None:
        letter = generate_cover_letter(_graduate_job(), _master_cv(), _profile())
        assert "internship" not in letter.lower(), (
            "Cover letter for a Graduate permanent role says 'internship'."
        )

    def test_adjust_summary_cdi_replaces_internship_phrase(self) -> None:
        summary = "Available for a 6 month Data Science internship in France."
        result = _adjust_summary_for_contract(summary, _cdi_job())
        assert "internship" not in result.lower(), (
            f"After adjustment for CDI, summary still contains 'internship': {result!r}"
        )

    def test_adjust_summary_stage_preserves_internship_phrase(self) -> None:
        summary = "Available for a 6 month Data Science internship in France."
        result = _adjust_summary_for_contract(summary, _stage_job())
        assert "internship" in result.lower() or "stage" in result.lower()


# ---------------------------------------------------------------------------
# Phase 1C: CV summary tail for junior/graduate roles must NOT say "internship"
# ---------------------------------------------------------------------------

class TestTailoredSummaryContractTail:
    def _make_master_cv(self) -> MasterCV:
        return _master_cv()

    def _make_profile(self) -> CandidateProfile:
        return _profile()

    def test_stage_summary_mentions_internship(self) -> None:
        result = _tailored_summary(
            _stage_job(), self._make_master_cv(), self._make_profile(),
            original_body="I am a data scientist.",
            french=False,
        )
        # stage jobs: OK to say "internship" / "Seeking a 6-month"
        assert "internship" in result.lower() or "stage" in result.lower() or "6-month" in result.lower()

    def test_junior_cdi_summary_does_not_say_internship(self) -> None:
        result = _tailored_summary(
            _junior_cdi_job(), self._make_master_cv(), self._make_profile(),
            original_body="I am a data scientist.",
            french=False,
        )
        assert "internship" not in result.lower() and "6-month" not in result.lower(), (
            f"Summary tail for Junior CDI still says 'internship': {result!r}. "
            "Fix _detect_contract_family (remove 'junior' from stage regex)."
        )

    def test_cdi_summary_does_not_say_internship(self) -> None:
        result = _tailored_summary(
            _cdi_job(), self._make_master_cv(), self._make_profile(),
            original_body="I am a data scientist.",
            french=False,
        )
        assert "internship" not in result.lower() and "6-month" not in result.lower()
