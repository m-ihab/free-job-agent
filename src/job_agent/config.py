"""Configuration management for free-job-agent."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from job_agent.secrets import load_local_env
try:
    from pydantic.v1 import BaseModel, Field
except Exception:  # pragma: no cover
    from pydantic import BaseModel, Field  # type: ignore[assignment]


def _default_data_dir() -> Path:
    data_dir = os.environ.get("JOB_AGENT_DATA_DIR")
    if data_dir:
        return Path(data_dir).expanduser()
    home = os.environ.get("HOME")
    if home:
        return Path(home).expanduser() / ".job_agent"
    cwd_profiles = Path.cwd() / "profiles"
    if _has_profile_bundle(cwd_profiles):
        return Path.cwd() / ".job_agent"
    return Path.home() / ".job_agent"


def _has_profile_bundle(path: Path) -> bool:
    return all(
        (path / name).exists()
        for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]
    )


def _default_profiles_dir(data_dir: Path) -> Path:
    profiles_dir = os.environ.get("JOB_AGENT_PROFILES_DIR")
    if profiles_dir:
        return Path(profiles_dir).expanduser()
    cwd_profiles = Path.cwd() / "profiles"
    if _has_profile_bundle(cwd_profiles):
        return cwd_profiles
    return data_dir / "profiles"


class AppConfig(BaseModel):
    """Application configuration.

    Defaults to ~/.job_agent for installed use, but tests can redirect HOME.
    """
    data_dir: Path = Field(default_factory=_default_data_dir)
    db_path: Optional[Path] = None
    outputs_dir: Optional[Path] = None
    profiles_dir: Optional[Path] = None
    examples_dir: Optional[Path] = None
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"
    ollama_enabled: bool = False
    default_locale: str = "en"
    log_level: str = "INFO"
    min_fit_score: int = 70
    obsidian_vault_dir: Optional[Path] = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        if self.db_path is None:
            self.db_path = self.data_dir / "jobs.db"
        if self.outputs_dir is None:
            self.outputs_dir = self.data_dir / "outputs"
        if self.profiles_dir is None:
            self.profiles_dir = _default_profiles_dir(self.data_dir)
        if self.examples_dir is None:
            self.examples_dir = Path.cwd() / "examples"
        if self.obsidian_vault_dir is None:
            self.obsidian_vault_dir = Path.cwd() / "second-brain"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        assert self.outputs_dir is not None
        assert self.profiles_dir is not None
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        load_local_env()
        env_path = os.environ.get("JOB_AGENT_CONFIG")
        if path is None and env_path:
            path = Path(env_path)
        if path is None:
            path = _default_data_dir() / "config.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return cls(**data)
        return cls()

    def save(self, path: Optional[Path] = None) -> None:
        if path is None:
            path = self.data_dir / "config.json"
        self.ensure_dirs()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.dict(), f, indent=2, default=str)
