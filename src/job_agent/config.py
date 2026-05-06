"""Configuration management for free-job-agent."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Application configuration."""
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".job_agent")
    db_path: Optional[Path] = None
    outputs_dir: Optional[Path] = None
    profiles_dir: Optional[Path] = None
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"
    ollama_enabled: bool = False
    default_locale: str = "en"
    log_level: str = "INFO"

    def model_post_init(self, __context: object) -> None:
        if self.db_path is None:
            self.db_path = self.data_dir / "jobs.db"
        if self.outputs_dir is None:
            self.outputs_dir = self.data_dir / "outputs"
        if self.profiles_dir is None:
            self.profiles_dir = self.data_dir / "profiles"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
        self.profiles_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        if path is None:
            path = Path.home() / ".job_agent" / "config.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            return cls(**data)
        return cls()

    def save(self, path: Optional[Path] = None) -> None:
        if path is None:
            path = self.data_dir / "config.json"
        self.ensure_dirs()
        with open(path, "w") as f:
            json.dump(self.model_dump(mode="json"), f, indent=2, default=str)
