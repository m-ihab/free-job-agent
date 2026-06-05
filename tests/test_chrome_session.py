"""TDD Area 3: Chrome apply session generation.

Tests cover generate_batch_instructions behavior:
- empty DB → empty list + file written
- ready packets above threshold → included
- low-score packets → excluded
- limit respected
- file content contains expected sections
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from unittest.mock import patch

from job_agent.apply_bridge import ApplyCandidate, build_chrome_instruction, generate_batch_instructions
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.fingerprint import set_fingerprint
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, PacketStatus
from job_agent.tracker import ApplicationTracker

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / ".job_agent"
    profiles_dir = data_dir / "profiles"
    outputs_dir = data_dir / "outputs"
    profiles_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        shutil.copyfile(EXAMPLES_DIR / name, profiles_dir / name)
    return AppConfig(
        data_dir=data_dir,
        profiles_dir=profiles_dir,
        outputs_dir=outputs_dir,
        db_path=data_dir / "jobs.db",
    )


_job_counter = 0


def _ready_job_and_packet(db: Database, score: float = 80.0, apply_url: str | None = None) -> tuple[JobListing, ApplicationPacket]:
    global _job_counter
    _job_counter += 1
    tracker = ApplicationTracker(db)
    unique_url = apply_url or f"https://ex{_job_counter}.com/apply/{_job_counter}"
    job = set_fingerprint(JobListing(
        title=f"Data Scientist #{_job_counter}",
        company=f"Acme{_job_counter}",
        apply_url=unique_url,
        status=JobStatus.PACKET_READY,
        fit_score=score,
    ))
    tracker.add_job(job)
    packet = ApplicationPacket(
        job_id=job.id,
        status=PacketStatus.READY,
        fit_score=score,
        fit_decision="apply",
        cover_letter_md="Dear Team,\n\nI'd love to join.",
        tailored_cv_pdf_path="/fake/cv.pdf",
        qa_answers={"Work in EU?": "Yes"},
    )
    db.save_packet(packet)
    return job, packet


# ── generate_batch_instructions ────────────────────────────────────────────────

def _patch_db(db: Database):
    """Context manager: patch apply_bridge._get_db to return the given test DB."""
    return patch("job_agent.apply_bridge._get_db", return_value=db)


class TestGenerateBatchInstructions:
    def test_empty_db_returns_empty_list_and_writes_file(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        db = Database(config.db_path)
        db.initialize()
        out = tmp_path / "session.md"
        with _patch_db(db):
            candidates, path = generate_batch_instructions(min_score=65, limit=10, output_path=out)
        assert candidates == []
        assert path.exists()
        assert "No ready applications" in path.read_text(encoding="utf-8")

    def test_returns_ready_packet_above_threshold(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        db = Database(config.db_path)
        db.initialize()
        _ready_job_and_packet(db, score=80.0)
        out = tmp_path / "session.md"
        with _patch_db(db):
            candidates, path = generate_batch_instructions(min_score=65, limit=10, output_path=out)
        assert len(candidates) == 1

    def test_excludes_packet_below_min_score(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        db = Database(config.db_path)
        db.initialize()
        _ready_job_and_packet(db, score=40.0)
        out = tmp_path / "session.md"
        with _patch_db(db):
            candidates, _ = generate_batch_instructions(min_score=65, limit=10, output_path=out)
        assert len(candidates) == 0

    def test_respects_limit(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        db = Database(config.db_path)
        db.initialize()
        for _ in range(5):
            _ready_job_and_packet(db, score=80.0)
        out = tmp_path / "session.md"
        with _patch_db(db):
            candidates, _ = generate_batch_instructions(min_score=65, limit=3, output_path=out)
        assert len(candidates) <= 3

    def test_session_file_contains_application_blocks(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        db = Database(config.db_path)
        db.initialize()
        _ready_job_and_packet(db, score=80.0)
        out = tmp_path / "session.md"
        with _patch_db(db):
            candidates, path = generate_batch_instructions(min_score=65, limit=10, output_path=out)
        content = path.read_text(encoding="utf-8")
        assert "STEP 1" in content
        assert "SAFETY RULES" in content

    def test_session_file_has_header(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        db = Database(config.db_path)
        db.initialize()
        _ready_job_and_packet(db, score=80.0)
        out = tmp_path / "session.md"
        with _patch_db(db):
            _, path = generate_batch_instructions(min_score=65, limit=10, output_path=out)
        content = path.read_text(encoding="utf-8")
        assert "Claude-in-Chrome Apply Session" in content

    def test_excludes_already_submitted_jobs(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        db = Database(config.db_path)
        db.initialize()
        tracker = ApplicationTracker(db)
        job, packet = _ready_job_and_packet(db, score=80.0)
        tracker.update_status(job.id, JobStatus.MANUALLY_SUBMITTED)
        out = tmp_path / "session.md"
        with _patch_db(db):
            candidates, _ = generate_batch_instructions(min_score=65, limit=10, output_path=out)
        assert len(candidates) == 0

    def test_excludes_job_without_apply_url(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        db = Database(config.db_path)
        db.initialize()
        tracker = ApplicationTracker(db)
        job = set_fingerprint(JobListing(
            title="Data Engineer No URL",
            company="CorpNoURL",
            apply_url=None,
            fit_score=90.0,
            status=JobStatus.PACKET_READY,
        ))
        tracker.add_job(job)
        db.save_packet(ApplicationPacket(
            job_id=job.id, status=PacketStatus.READY, fit_score=90.0,
        ))
        out = tmp_path / "session.md"
        with _patch_db(db):
            candidates, _ = generate_batch_instructions(min_score=65, limit=10, output_path=out)
        assert len(candidates) == 0


# ── build_chrome_instruction content ──────────────────────────────────────────

class TestBuildChromeInstructionContent:
    def _candidate(self, score: float = 82.0) -> ApplyCandidate:
        job = JobListing(
            id="j-test",
            title="ML Engineer",
            company="RoboCo",
            apply_url="https://roboco.ai/apply",
            fit_score=score,
        )
        packet = ApplicationPacket(
            id="pkt-test",
            job_id="j-test",
            status=PacketStatus.READY,
            fit_score=score,
            fit_decision="apply",
            cover_letter_md="Dear Hiring Team,\n\nI am excited.",
        )
        return ApplyCandidate(
            job=job, packet=packet,
            cv_pdf_path="/home/user/cv.pdf",
            cover_letter_md=packet.cover_letter_md,
            qa_answers={"EU authorized?": "Yes, EU citizen"},
        )

    def test_instruction_contains_all_6_steps(self) -> None:
        text = build_chrome_instruction(self._candidate())
        for step_n in range(1, 7):
            assert f"STEP {step_n}" in text

    def test_instruction_contains_apply_url(self) -> None:
        text = build_chrome_instruction(self._candidate())
        assert "https://roboco.ai/apply" in text

    def test_instruction_contains_fit_score(self) -> None:
        text = build_chrome_instruction(self._candidate(score=77.0))
        assert "77" in text

    def test_instruction_contains_qa_answers(self) -> None:
        text = build_chrome_instruction(self._candidate())
        assert "EU citizen" in text

    def test_instruction_enforces_no_auto_submit(self) -> None:
        text = build_chrome_instruction(self._candidate())
        assert "confirmation" in text.lower()
        assert ("never invent" in text.lower() or "never submit" in text.lower() or "safety rules" in text.lower())
