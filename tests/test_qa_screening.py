"""Tests for conservative screening-question extraction and packet QA handling."""
from pathlib import Path
import shutil

from job_agent.config import AppConfig
from job_agent.db import Database
from job_agent.fingerprint import set_fingerprint
from job_agent.generator.qa import (
    MANUAL_REVIEW_MARKER,
    build_screening_answers_for_job,
    extract_screening_questions,
)
from job_agent.pipeline import generate_packet_for_job
from job_agent.schemas.job import JobListing
from job_agent.tracker import ApplicationTracker

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _copy_profiles(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / ".job_agent"
    profiles_dir = data_dir / "profiles"
    outputs_dir = data_dir / "outputs"
    profiles_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        shutil.copyfile(EXAMPLES_DIR / name, profiles_dir / name)
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir, outputs_dir=outputs_dir, db_path=data_dir / "jobs.db")


def test_extract_screening_questions_is_conservative():
    text = """Screening questions
- Are you authorized to work in France?
2. Do you require visa sponsorship?
Python and Docker are required.
"""
    assert extract_screening_questions(text) == [
        "Are you authorized to work in France?",
        "Do you require visa sponsorship?",
    ]


def test_build_screening_answers_detected_questions_and_bank(sample_qa_profile):
    job = JobListing(
        title="Backend Engineer",
        company="ExampleCo",
        raw_text="Application question: Are you authorized to work in France?",
    )
    answers = build_screening_answers_for_job(job, sample_qa_profile)
    by_question = {answer.question: answer for answer in answers}

    assert "Are you authorized to work in France?" in by_question
    assert "authorized" in by_question["Are you authorized to work in France?"].answer
    assert any("sponsorship" in question.lower() for question in by_question)


def test_packet_marks_unknown_detected_screening_question_for_review(tmp_path):
    config = _copy_profiles(tmp_path)
    db = Database(config.db_path)
    db.initialize()
    tracker = ApplicationTracker(db)
    job = JobListing(
        title="Senior Python Engineer",
        company="Example Analytics",
        location="Remote",
        remote=True,
        raw_text="Senior Python Engineer\nApplication question: What is your favorite database color?\nRequirements:\n- Python\n- PostgreSQL",
        description="Build Python APIs.",
        requirements=["Python", "PostgreSQL"],
        tech_stack=["python", "postgresql"],
        apply_url="https://example.com/apply",
    )
    tracker.add_job(set_fingerprint(job))

    packet = generate_packet_for_job(config, job.id)

    assert packet.status.value == "NEEDS_REVIEW"
    assert "screening_question_needs_manual_review" in packet.risk_flags
    assert packet.qa_answers["What is your favorite database color?"] == MANUAL_REVIEW_MARKER
    assistant_path = Path(next(a.path for a in packet.artifacts if a.kind == "assistant_html"))
    assistant_html = assistant_path.read_text(encoding="utf-8")
    assert "needs-review" in assistant_html
    assert "does not submit forms" in assistant_html


def test_repeated_packet_generations_keep_distinct_versions(tmp_path):
    config = _copy_profiles(tmp_path)
    db = Database(config.db_path)
    db.initialize()
    tracker = ApplicationTracker(db)
    job = JobListing(
        title="Senior Python Engineer",
        company="Example Analytics",
        location="Remote",
        remote=True,
        raw_text="Senior Python Engineer\nRequirements:\n- Python\n- PostgreSQL",
        description="Build Python APIs.",
        requirements=["Python", "PostgreSQL"],
        tech_stack=["python", "postgresql"],
        apply_url="https://example.com/apply",
    )
    tracker.add_job(set_fingerprint(job))

    first = generate_packet_for_job(config, job.id)
    second = generate_packet_for_job(config, job.id)

    assert first.id != second.id
    assert first.version == 1
    assert second.version == 2
    assert "packet_v1" in first.tailored_cv_pdf_path
    assert "packet_v2" in second.tailored_cv_pdf_path
    assert len(db.get_packets_for_job(job.id)) == 2
