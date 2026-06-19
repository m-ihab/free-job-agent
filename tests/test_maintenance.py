"""Tests for one-shot maintenance helpers (dedupe, rescan, source probing).

Network is fully mocked — ``validate_cac40_sources`` must never hit a real ATS.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from job_agent import maintenance
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.schemas.job import JobListing


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


def _db(config: AppConfig) -> Database:
    db = Database(config.db_path)
    db.initialize()
    return db


def _job(**overrides) -> JobListing:
    # A distinct, non-empty stored fingerprint is required so two jobs can both
    # be inserted (the DB has a partial UNIQUE index on fingerprint != '').
    # The tightened algorithm may still map their *content* to one fingerprint.
    base = dict(title="Data Scientist", company="ACME", location="Paris")
    base.update(overrides)
    return JobListing(**base)


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


# --- dedupe_jobs (pure DB, no mock) --------------------------------------

def test_dedupe_jobs_dry_run_reports_duplicates_without_deleting(config):
    # Two rows with identical *content* but distinct stored fingerprints — the
    # exact scenario the tightened algorithm is meant to collapse.
    db = _db(config)
    db.save_job(_job(fingerprint="legacy-a"))
    db.save_job(_job(fingerprint="legacy-b"))

    report = maintenance.dedupe_jobs(config, dry_run=True)

    assert report["removed"] == 1
    assert report["dry_run"] is True
    assert len(_db(config).list_jobs(limit=None)) == 2  # nothing deleted in dry-run


def test_dedupe_jobs_keeps_distinct_jobs(config):
    db = _db(config)
    db.save_job(_job(title="Data Scientist", fingerprint="legacy-a"))
    db.save_job(_job(title="ML Engineer", company="Other", fingerprint="legacy-b"))

    report = maintenance.dedupe_jobs(config)

    assert report["removed"] == 0
    assert report["fingerprints_refreshed"] == 2  # both stale fps rewritten
    assert len(_db(config).list_jobs(limit=None)) == 2


# --- validate_cac40_sources (mocked network) -----------------------------

def test_validate_cac40_marks_dead_sources_on_404(config, monkeypatch):
    monkeypatch.setattr(
        maintenance.requests, "get", lambda *a, **k: _FakeResponse(404)
    )

    report = maintenance.validate_cac40_sources(config)

    assert report["healthy"] == 0
    assert report["broken"] >= 1
    assert any(r["status"] == "dead" for r in report["results"])


def test_validate_cac40_reports_healthy_on_200(config, monkeypatch):
    monkeypatch.setattr(
        maintenance.requests, "get", lambda *a, **k: _FakeResponse(200)
    )

    report = maintenance.validate_cac40_sources(config)

    assert report["healthy"] >= 1
    assert report["broken"] == 0


def test_validate_cac40_classifies_transient_status(config, monkeypatch):
    monkeypatch.setattr(
        maintenance.requests, "get", lambda *a, **k: _FakeResponse(500)
    )

    report = maintenance.validate_cac40_sources(config)

    assert report["healthy"] == 0
    assert report["broken"] == 0
    assert any(r["status"] == "transient" for r in report["results"])


def test_validate_cac40_records_errors_without_crashing(config, monkeypatch):
    def _boom(*a, **k):
        raise ConnectionError("network down")

    monkeypatch.setattr(maintenance.requests, "get", _boom)

    report = maintenance.validate_cac40_sources(config)

    assert any(r["status"] == "error" for r in report["results"])


# --- clear_broken_sources -------------------------------------------------

def test_clear_broken_sources_forgets_all_entries(config):
    db = _db(config)
    db.mark_source_broken("greenhouse", "deadco", status_code=404, reason="probe")

    result = maintenance.clear_broken_sources(config)

    assert result["cleared"] >= 1
    assert _db(config).list_broken_sources() == []
