"""Shared low-level primitives for CV Studio.

These are the filesystem and draft helpers that the public ``cv_studio`` module
and its asset / project helper modules all build on. This module imports none of
them back, so it sits at the bottom of the import graph (no cycles).
"""
from __future__ import annotations

from pathlib import Path

from job_agent.config import AppConfig


STUDIO_DIRNAME = "cv_studio"


_TEXT_ASSET_SUFFIXES = {".tex", ".sty", ".cls", ".bib", ".json", ".md", ".txt"}
_IMAGE_ASSET_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".pdf"}


def _studio_dir(config: AppConfig) -> Path:
    base = Path(config.data_dir or Path.cwd() / ".job_agent") / STUDIO_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _main_tex_path(config: AppConfig) -> Path | None:
    if not config.profiles_dir:
        return None
    candidate = Path(config.profiles_dir) / "main.tex"
    return candidate if candidate.exists() else None


def _draft_path(config: AppConfig) -> Path:
    return _studio_dir(config) / "draft.tex"


def _active_cv_text(config: AppConfig) -> tuple[str, Path | None, str]:
    """Return the editable CV source, preferring the Studio draft."""
    draft = _draft_path(config)
    if draft.exists():
        return draft.read_text(encoding="utf-8"), draft, "draft"
    main = _main_tex_path(config)
    if main and main.exists():
        return main.read_text(encoding="utf-8"), main, "main"
    return "", None, "empty"


def _write_draft(config: AppConfig, text: str) -> Path:
    draft = _draft_path(config)
    draft.write_text(text or "", encoding="utf-8")
    return draft


def _profiles_root(config: AppConfig) -> Path:
    if not config.profiles_dir:
        raise ValueError("Profiles directory is not configured.")
    return Path(config.profiles_dir).resolve()


def _safe_asset_path(config: AppConfig, name: str) -> Path:
    """Return the safe path for ``name`` inside ``profiles/`` or raise."""
    root = _profiles_root(config)
    # No directory traversal — strip any leading slashes and ".."
    cleaned = Path(name).name
    if not cleaned:
        raise ValueError("Asset name required.")
    candidate = (root / cleaned).resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Asset must live in profiles/.")
    return candidate
