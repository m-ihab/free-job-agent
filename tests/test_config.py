from pathlib import Path

from job_agent.config import AppConfig


def test_project_profiles_make_local_data_dir_default(tmp_path, monkeypatch):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        (profiles_dir / name).write_text("{}", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.delenv("JOB_AGENT_DATA_DIR", raising=False)
    monkeypatch.delenv("JOB_AGENT_PROFILES_DIR", raising=False)

    config = AppConfig()

    assert config.data_dir == tmp_path / ".job_agent"
    assert config.profiles_dir == profiles_dir


def test_profile_dir_env_override(tmp_path, monkeypatch):
    explicit_profiles = tmp_path / "custom_profiles"
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(explicit_profiles))

    config = AppConfig(data_dir=tmp_path / "data")

    assert config.profiles_dir == explicit_profiles
