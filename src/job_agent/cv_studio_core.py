"""Shared low-level primitives for CV Studio.

These are the filesystem and draft helpers that the public ``cv_studio`` module
and its asset / project helper modules all build on. This module imports none of
them back, so it sits at the bottom of the import graph (no cycles).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from job_agent.config import AppConfig


STUDIO_DIRNAME = "cv_studio"

# A valid moderncv/LaTeX CV carries the ``\documentclass`` + ``\begin{document}``
# markers. The byte floor is a secondary check for truncated documents that kept
# their preamble but lost their body; kept low so a short CV still passes.
MIN_TEX_BYTES = 100
# When overwriting an existing valid ``main.tex``, reject a candidate that is a
# tiny fraction of the current file (almost always a truncated/placeholder
# draft, never a legitimate edit).
MIN_SHRINK_RATIO = 0.25


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


# -----------------------------------------------------------------------------
# main.tex integrity: validation + version history
# -----------------------------------------------------------------------------


def is_valid_latex_cv(text: str | None) -> bool:
    """True only for text that is plausibly a complete LaTeX CV document.

    Guards the promote path so a placeholder/JSON/truncated draft can never be
    written over the user's real ``profiles/main.tex`` again.
    """
    if not text:
        return False
    if len(text.encode("utf-8")) < MIN_TEX_BYTES:
        return False
    return r"\documentclass" in text and r"\begin{document}" in text


def validate_promote(new_text: str | None, current_main: Path | None) -> tuple[bool, str]:
    """Decide whether ``new_text`` may overwrite ``current_main``.

    Returns ``(ok, reason)``. ``reason`` is empty when ok, else a short machine
    token the UI maps to a friendly message.
    """
    if not is_valid_latex_cv(new_text):
        return False, "not_latex_document"
    if current_main and current_main.exists():
        try:
            current_bytes = current_main.stat().st_size
        except OSError:
            current_bytes = 0
        new_bytes = len((new_text or "").encode("utf-8"))
        # Only block shrink when the existing file is itself a real document;
        # if main.tex is already a tiny placeholder, any valid draft may replace it.
        if current_bytes >= MIN_TEX_BYTES and new_bytes < current_bytes * MIN_SHRINK_RATIO:
            return False, "suspicious_shrink"
    return True, ""


def _history_dir(config: AppConfig) -> Path:
    """Gitignored snapshot folder for ``main.tex`` versions (under profiles/)."""
    root = _profiles_root(config)
    hist = root / ".history"
    hist.mkdir(parents=True, exist_ok=True)
    return hist


def snapshot_main_tex(config: AppConfig) -> Path | None:
    """Copy the current ``main.tex`` into ``profiles/.history`` with a timestamp.

    No-op (returns ``None``) when there is no existing main.tex to snapshot.
    """
    main = _main_tex_path(config)
    if not main or not main.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = _history_dir(config) / f"main.{ts}.tex"
    # Avoid clobbering a snapshot taken within the same second.
    counter = 1
    while target.exists():
        target = _history_dir(config) / f"main.{ts}-{counter}.tex"
        counter += 1
    target.write_bytes(main.read_bytes())
    return target


def list_main_versions(config: AppConfig) -> list[dict[str, Any]]:
    """Return saved ``main.tex`` snapshots, newest first."""
    try:
        hist = _history_dir(config)
    except ValueError:
        return []
    versions: list[dict[str, Any]] = []
    for path in sorted(hist.glob("main.*.tex"), reverse=True):
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        versions.append({"name": path.name, "size": size})
    return versions


def restore_main_version(config: AppConfig, name: str) -> dict[str, Any]:
    """Restore a snapshot from ``profiles/.history`` back onto ``main.tex``.

    Snapshots the current main.tex first so the restore is itself reversible.
    """
    cleaned = Path(name).name
    if not cleaned.startswith("main.") or not cleaned.endswith(".tex"):
        return {"ok": False, "reason": "bad_version_name"}
    source = _history_dir(config) / cleaned
    if not source.exists():
        return {"ok": False, "reason": "version_not_found"}
    text = source.read_text(encoding="utf-8")
    if not is_valid_latex_cv(text):
        return {"ok": False, "reason": "not_latex_document"}
    snapshot_main_tex(config)
    main_path = _profiles_root(config) / "main.tex"
    main_path.write_text(text, encoding="utf-8")
    return {"ok": True, "main_path": str(main_path), "restored_from": cleaned}
