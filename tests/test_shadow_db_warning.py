"""warn_on_shadow_db: the 2026-07-11 "all my jobs are gone" guard.

A launch that resolves an emptier database than an existing sibling
(.job_agent under cwd or home) must log a loud warning — unless the data dir
was pinned explicitly (JOB_AGENT_DATA_DIR), which is how launchers run.
"""
from __future__ import annotations

import logging
import sqlite3

import pytest

from job_agent.config import AppConfig
from job_agent.ui import services


def _make_db(path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY)")
    con.executemany("INSERT INTO jobs (id) VALUES (?)", [(f"j{i}",) for i in range(rows)])
    con.commit()
    con.close()


@pytest.fixture
def isolated_homes(tmp_path, monkeypatch):
    """Fake home + cwd so the candidate probing never touches real user data."""
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    (cwd / ".job_agent").mkdir(parents=True)
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOMEDRIVE", "")
    monkeypatch.setenv("HOMEPATH", "")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("JOB_AGENT_DATA_DIR", raising=False)
    monkeypatch.delenv("JOB_AGENT_SILENCE_SHADOW_DB", raising=False)
    return home, cwd


def test_warns_when_active_db_is_emptier_than_sibling(isolated_homes, tmp_path, caplog):
    home, cwd = isolated_homes
    active = tmp_path / "active" / "jobs.db"
    _make_db(active, rows=0)
    _make_db(cwd / ".job_agent" / "jobs.db", rows=5)
    config = AppConfig(data_dir=tmp_path / "active")

    with caplog.at_level(logging.WARNING, logger="job_agent.ui.services"):
        services.warn_on_shadow_db(config)

    assert any("holds 5" in rec.getMessage() for rec in caplog.records), caplog.text


def test_silent_when_data_dir_is_pinned(isolated_homes, tmp_path, caplog, monkeypatch):
    home, cwd = isolated_homes
    active = tmp_path / "active" / "jobs.db"
    _make_db(active, rows=0)
    _make_db(cwd / ".job_agent" / "jobs.db", rows=5)
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "active"))
    config = AppConfig(data_dir=tmp_path / "active")

    with caplog.at_level(logging.WARNING, logger="job_agent.ui.services"):
        services.warn_on_shadow_db(config)

    assert not caplog.records


def test_silent_when_active_db_is_the_fuller_one(isolated_homes, tmp_path, caplog):
    home, cwd = isolated_homes
    active = cwd / ".job_agent" / "jobs.db"
    _make_db(active, rows=9)
    _make_db(home / ".job_agent" / "jobs.db", rows=2)
    config = AppConfig(data_dir=cwd / ".job_agent")

    with caplog.at_level(logging.WARNING, logger="job_agent.ui.services"):
        services.warn_on_shadow_db(config)

    assert not caplog.records
