"""Tests for apply_bridge — Chrome auto-apply instruction generator."""
from __future__ import annotations

import pytest

from job_agent.apply_bridge import ApplyCandidate, build_chrome_instruction
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, PacketStatus


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def job_linkedin() -> JobListing:
    return JobListing(
        id="job-001",
        title="Data Scientist",
        company="Acme Corp",
        location="Paris, France",
        apply_url="https://www.linkedin.com/jobs/view/123456",
        tech_stack=["Python", "pandas", "scikit-learn"],
        description="Data scientist role in Paris.",
        status=JobStatus.PACKET_READY,
    )


@pytest.fixture()
def job_no_url() -> JobListing:
    return JobListing(
        id="job-002",
        title="ML Engineer",
        company="Beta Inc",
        apply_url=None,
        status=JobStatus.NEW,
    )


@pytest.fixture()
def packet_ready(job_linkedin: JobListing) -> ApplicationPacket:
    return ApplicationPacket(
        id="pkt-001",
        job_id=job_linkedin.id,
        status=PacketStatus.READY,
        fit_score=82.0,
        fit_decision="apply",
        cover_letter_md="Dear Hiring Manager,\n\nI am excited to apply...",
        tailored_cv_pdf_path="/home/user/.job_agent/outputs/job-001/cv.pdf",
        qa_answers={
            "Are you eligible to work in France?": "Yes, EU citizen",
            "Do you speak French?": "Yes, B2 level",
            "Years of experience with Python?": "4",
        },
    )


@pytest.fixture()
def candidate(job_linkedin: JobListing, packet_ready: ApplicationPacket) -> ApplyCandidate:
    return ApplyCandidate(
        job=job_linkedin,
        packet=packet_ready,
        cv_pdf_path=packet_ready.tailored_cv_pdf_path,
        cover_letter_md=packet_ready.cover_letter_md,
        qa_answers=packet_ready.qa_answers,
    )


# ── build_chrome_instruction ──────────────────────────────────────────────────

class TestBuildChromeInstruction:
    def test_contains_apply_url(self, candidate: ApplyCandidate) -> None:
        text = build_chrome_instruction(candidate)
        assert "https://www.linkedin.com/jobs/view/123456" in text

    def test_contains_job_title_and_company(self, candidate: ApplyCandidate) -> None:
        text = build_chrome_instruction(candidate)
        assert "Data Scientist" in text
        assert "Acme Corp" in text

    def test_contains_fit_score(self, candidate: ApplyCandidate) -> None:
        text = build_chrome_instruction(candidate)
        assert "82" in text

    def test_contains_qa_answers(self, candidate: ApplyCandidate) -> None:
        text = build_chrome_instruction(candidate)
        assert "EU citizen" in text
        assert "B2 level" in text

    def test_contains_cv_path(self, candidate: ApplyCandidate) -> None:
        text = build_chrome_instruction(candidate)
        assert "cv.pdf" in text

    def test_contains_cover_letter_preview(self, candidate: ApplyCandidate) -> None:
        text = build_chrome_instruction(candidate)
        assert "Dear Hiring Manager" in text

    def test_safety_rules_present(self, candidate: ApplyCandidate) -> None:
        text = build_chrome_instruction(candidate)
        assert "Never invent" in text or "never invent" in text.lower()
        assert "confirmation" in text.lower()

    def test_no_cv_path_fallback_message(self, job_linkedin: JobListing, packet_ready: ApplicationPacket) -> None:
        c = ApplyCandidate(
            job=job_linkedin,
            packet=packet_ready,
            cv_pdf_path=None,
            cover_letter_md="",
            qa_answers={},
        )
        text = build_chrome_instruction(c)
        assert "no PDF" in text or "manually" in text

    def test_packet_id_in_output(self, candidate: ApplyCandidate) -> None:
        text = build_chrome_instruction(candidate)
        assert "pkt-001" in text
