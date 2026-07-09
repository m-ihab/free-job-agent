"""R1: AppConfig.resolved_db_path — absolute, expanded DB path."""
from pathlib import Path

from job_agent.config import AppConfig


def test_resolved_db_path_is_absolute(tmp_path):
    cfg = AppConfig(data_dir=tmp_path)
    resolved = cfg.resolved_db_path
    assert resolved.is_absolute()
    assert resolved == (tmp_path / "jobs.db").resolve()


def test_resolved_db_path_honours_explicit_db_path(tmp_path):
    custom = tmp_path / "nested" / "custom.db"
    cfg = AppConfig(data_dir=tmp_path, db_path=custom)
    assert cfg.resolved_db_path == custom.resolve()


def test_resolved_db_path_expands_user(tmp_path, monkeypatch):
    # A '~' in db_path must expand to the home directory, not stay literal.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows home
    cfg = AppConfig(data_dir=tmp_path, db_path=Path("~/agent.db"))
    resolved = cfg.resolved_db_path
    assert "~" not in str(resolved)
    assert resolved.is_absolute()
