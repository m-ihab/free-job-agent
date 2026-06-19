"""Logging configuration: env-driven level + idempotent setup + guarded-path logging."""
from __future__ import annotations

import logging

from job_agent.logging_config import configure_logging, resolve_level
from job_agent.schemas.job import JobListing
from job_agent.timeutil import utc_now


def test_resolve_level_defaults_to_warning(monkeypatch):
    monkeypatch.delenv("JOB_AGENT_LOG_LEVEL", raising=False)
    assert resolve_level() == logging.WARNING


def test_resolve_level_reads_env(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_LOG_LEVEL", "debug")
    assert resolve_level() == logging.DEBUG


def test_resolve_level_unknown_falls_back_to_warning():
    assert resolve_level("not-a-level") == logging.WARNING


def test_configure_logging_is_idempotent(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_LOG_LEVEL", "INFO")
    configure_logging(force=True)
    handler_count = len(logging.getLogger().handlers)
    configure_logging()  # second call must not stack handlers
    assert len(logging.getLogger().handlers) == handler_count


def test_corrupt_cache_is_logged_not_silently_dropped(tmp_db, caplog):
    """A corrupt cached JSON payload must surface a warning, not vanish silently.

    Regression guard for WP-2: the former ``except Exception: return None`` on
    DB cache reads masked data corruption with no diagnostic trail.
    """
    job = JobListing(title="Data Scientist", company="ACME", source="paste", raw_text="x")
    tmp_db.save_job(job)
    # Plant an un-parseable enrichment payload directly, bypassing save_enrichment.
    with tmp_db._connect() as conn:
        conn.execute(
            "INSERT INTO enrichments (job_id, payload_json, updated_at) VALUES (?, ?, ?)",
            (job.id, "{ not valid json", utc_now()),
        )

    with caplog.at_level(logging.WARNING, logger="job_agent.db.database"):
        assert tmp_db.get_enrichment(job.id) is None

    assert any("Corrupt enrichment JSON" in rec.message for rec in caplog.records)
