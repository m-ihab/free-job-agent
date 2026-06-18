"""Logging configuration: env-driven level + idempotent setup."""
from __future__ import annotations

import logging

from job_agent.logging_config import configure_logging, resolve_level


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
