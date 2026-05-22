"""Local-only environment loading for API credentials."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


_ENV_LOADED = False


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if (value.startswith("\"") and value.endswith("\"")) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return key, value


def load_env_file(path: Path, *, override: bool = False) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return False
    for line in lines:
        parsed = _parse_env_line(line)
        if not parsed:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value
    return True


def load_local_env(paths: Iterable[Path] | None = None, *, override: bool = False) -> list[Path]:
    """Load local env files into os.environ without committing secrets to git."""
    global _ENV_LOADED
    if _ENV_LOADED and paths is None and not override:
        return []
    loaded: list[Path] = []
    if paths is None:
        candidates: list[Path] = []
        env_override = os.environ.get("JOB_AGENT_ENV_FILE", "").strip()
        if env_override:
            candidates.append(Path(env_override).expanduser())
        candidates.append(Path.cwd() / ".env.local")
        paths = candidates
    for path in paths:
        if load_env_file(path, override=override):
            loaded.append(path)
    _ENV_LOADED = True
    return loaded
