"""Behavioural tests for ``job_agent.pipeline`` and ``job_agent.tracker``.

These cover the deterministic orchestration branches without invoking AI, LaTeX,
or network: dedup on add, scoring side effects, the duplicate short-circuit in
``process_file``, artifact-kind detection in ``_write_text``, and the tracker's
status/history/enrichment/delete paths.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from job_agent import pipeline
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, PacketStatus
from job_agent.tracker import ApplicationTracker


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig(
        data_dir=tmp_path / "data",
        profiles_dir=tmp_path / "profiles",
        outputs_dir=tmp_path / "outputs",
    )
    cfg.ensure_dirs()
    Database(cfg.db_path).initialize()
    return cfg


def _job(title: str = "Data Scientist", company: str = "Acme") -> JobListing:
    return JobListing(title=title, company=company, source="paste",
                      raw_text=f"{title} at {company}", description="Build models")


# ── add_job_to_tracker dedup ─────────────────────────────────────────────────

def test_add_job_to_tracker_creates_then_dedupes(config):
    # Arrange / Act — first add creates, second add (same content) dedupes.
    job1, created1 = pipeline.add_job_to_tracker(config, _job())
    job2, created2 = pipeline.add_job_to_tracker(config, _job())

    # Assert
    assert created1 is True
    assert created2 is False
    assert job1.id == job2.id


def test_add_text_job_round_trips_through_tracker(config):
    # Act
    job, created = pipeline.add_text_job(
        config, "Senior Data Scientist building ML pipelines.", title="Data Scientist", company="Acme",
    )

    # Assert
    assert created is True
    tracker = ApplicationTracker(Database(config.db_path))
    assert tracker.get_job(job.id) is not None


# ── score_and_save side effects ──────────────────────────────────────────────

def test_score_and_save_sets_fit_fields_and_scored_status(config, sample_profile):
    # Arrange
    job, _ = pipeline.add_job_to_tracker(config, _job())

    # Act
    scored = pipeline.score_and_save(config, job, sample_profile)

    # Assert — score is computed and the job is marked SCORED with notes.
    assert scored.fit_score is not None
    assert isinstance(scored.fit_decision, str) and scored.fit_decision
    db = Database(config.db_path)
    assert db.get_job(job.id).status == JobStatus.SCORED


# ── process_file duplicate short-circuit ─────────────────────────────────────

def test_process_file_returns_none_packet_on_duplicate(config, tmp_path, monkeypatch):
    # Arrange — pre-seed the same job so process_file hits the dedup path.
    jd = tmp_path / "jd.txt"
    jd.write_text("Data Scientist at Acme. Build ML models in Python.", encoding="utf-8")
    pipeline.add_file_job(config, jd)

    # Guard: generate_packet_for_job must NOT be called on the duplicate path.
    def _boom(*a, **k):  # pragma: no cover - asserts it is never called
        raise AssertionError("packet generation should be skipped for duplicates")
    monkeypatch.setattr(pipeline, "generate_packet_for_job", _boom)

    # Act
    job, packet, created = pipeline.process_file(config, jd)

    # Assert
    assert created is False
    assert packet is None
    assert job is not None


# ── _write_text artifact-kind detection ──────────────────────────────────────

@pytest.mark.parametrize("filename, expected_kind", [
    ("assistant.html", "assistant_html"),
    ("cover_letter.md", "cover_letter_markdown"),
    ("cover_letter.html", "cover_letter_html"),
    ("cv.md", "cv_markdown"),
    ("cv.html", "cv_html"),
    ("cv.tex", "cv_latex"),
    ("latex_warning.txt", "latex_warning"),
    ("external_agent_prompt.md", "md"),
])
def test_write_text_detects_artifact_kind(tmp_path, filename, expected_kind):
    # Arrange / Act
    artifact = pipeline._write_text(tmp_path / filename, "content")

    # Assert
    assert artifact.kind == expected_kind
    assert Path(artifact.path).read_text(encoding="utf-8") == "content"
    assert artifact.sha256


# ── generate_packet_for_job: duplicate-packet guard ──────────────────────────

def test_generate_packet_for_job_blocks_duplicate_without_force(config, sample_profile, sample_master_cv, sample_qa_profile, monkeypatch):
    # Arrange — job already has a packet; loading the profile bundle is mocked.
    job, _ = pipeline.add_job_to_tracker(config, _job())
    db = Database(config.db_path)
    db.save_packet(ApplicationPacket(job_id=job.id, version=1, status=PacketStatus.READY))
    monkeypatch.setattr(
        pipeline, "load_profile_bundle",
        lambda cfg: (sample_profile, sample_master_cv, sample_qa_profile),
    )

    # Act / Assert — without --force the guard raises.
    with pytest.raises(RuntimeError, match="already exists"):
        pipeline.generate_packet_for_job(config, job.id, force=False)


def test_generate_packet_for_job_unknown_job_raises(config):
    with pytest.raises(ValueError, match="Job not found"):
        pipeline.generate_packet_for_job(config, "no-such-id")


# ── tracker behaviour ────────────────────────────────────────────────────────

def test_tracker_update_status_logs_event(tmp_db):
    # Arrange
    tracker = ApplicationTracker(tmp_db)
    job = tracker.add_job(_job())

    # Act
    tracker.update_status(job.id, JobStatus.SCORED, note="looks good")

    # Assert — status changed and a STATUS_CHANGED event was logged with the note.
    history = tracker.get_history(job.id)
    types = [e["event_type"] for e in history]
    assert "STATUS_CHANGED" in types
    status_event = next(e for e in history if e["event_type"] == "STATUS_CHANGED")
    assert status_event["event_data"]["note"] == "looks good"


def test_tracker_update_status_unknown_job_raises(tmp_db):
    tracker = ApplicationTracker(tmp_db)
    with pytest.raises(ValueError, match="Job not found"):
        tracker.update_status("missing", JobStatus.SCORED)


def test_tracker_delete_job_logs_removal_and_removes(tmp_db):
    # Arrange
    tracker = ApplicationTracker(tmp_db)
    job = tracker.add_job(_job())

    # Act
    removed_id = tracker.delete_job(job.id, note="cleanup")

    # Assert
    assert removed_id == job.id
    assert tracker.get_job(job.id) is None


def test_tracker_delete_unknown_job_raises(tmp_db):
    tracker = ApplicationTracker(tmp_db)
    with pytest.raises(ValueError, match="Job not found"):
        tracker.delete_job("missing")


def test_tracker_enrichment_round_trip(tmp_db):
    # Arrange
    tracker = ApplicationTracker(tmp_db)
    job = tracker.add_job(_job())

    # Act
    tracker.save_enrichment(job.id, {"rome": "M1805"})

    # Assert
    assert tracker.get_enrichment(job.id)["rome"] == "M1805"
    assert tracker.get_enrichment("missing") is None


def test_tracker_get_history_empty_for_unknown_job(tmp_db):
    tracker = ApplicationTracker(tmp_db)
    assert tracker.get_history("missing") == []
