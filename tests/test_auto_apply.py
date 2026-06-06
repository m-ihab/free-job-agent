from __future__ import annotations

from pathlib import Path

from job_agent.auto_apply import (
    _AUTO_APPLY_PROFILE_ENV,
    _USE_REAL_CHROME_PROFILE_ENV,
    _select_browser_profile,
)
from job_agent.config import AppConfig


def _config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / ".job_agent"
    return AppConfig(
        data_dir=data_dir,
        db_path=data_dir / "jobs.db",
        outputs_dir=data_dir / "outputs",
        profiles_dir=data_dir / "profiles",
    )


def test_auto_apply_uses_dedicated_profile_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(_AUTO_APPLY_PROFILE_ENV, raising=False)
    monkeypatch.delenv(_USE_REAL_CHROME_PROFILE_ENV, raising=False)

    selected = _select_browser_profile(_config(tmp_path))

    assert selected.label == "dedicated Job Agent"
    assert selected.path == tmp_path / ".job_agent" / "browser_profiles" / "auto_apply"
    assert selected.path.exists()


def test_auto_apply_accepts_custom_profile_dir(tmp_path, monkeypatch):
    custom = tmp_path / "custom-browser-profile"
    monkeypatch.setenv(_AUTO_APPLY_PROFILE_ENV, str(custom))
    monkeypatch.delenv(_USE_REAL_CHROME_PROFILE_ENV, raising=False)

    selected = _select_browser_profile(_config(tmp_path))

    assert selected.label == "custom Job Agent"
    assert selected.path == custom
    assert selected.path.exists()


def test_real_chrome_opt_in_falls_back_when_profile_is_locked(tmp_path, monkeypatch):
    real_profile = tmp_path / "Chrome" / "User Data"
    real_profile.mkdir(parents=True)
    (real_profile / "SingletonLock").write_text("locked", encoding="utf-8")
    monkeypatch.setenv(_USE_REAL_CHROME_PROFILE_ENV, "1")
    monkeypatch.delenv(_AUTO_APPLY_PROFILE_ENV, raising=False)
    monkeypatch.setattr("job_agent.auto_apply._find_chrome_profile", lambda: str(real_profile))

    selected = _select_browser_profile(_config(tmp_path))

    assert selected.label == "dedicated Job Agent"
    assert "already in use" in selected.warning
    assert selected.path != real_profile
