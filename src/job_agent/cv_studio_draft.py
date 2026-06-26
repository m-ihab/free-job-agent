"""CV Studio — draft lifecycle: load, save, reset, and promote to main.tex."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from job_agent.config import AppConfig
from job_agent.cv_studio_core import (
    _draft_path,
    _main_tex_path,
    snapshot_main_tex,
    validate_promote,
)
from job_agent.cv_studio_sections import _extract_section_titles, section_display_name
from job_agent.renderer.latex_render import available_latex_compiler, detect_cvlang

try:
    from job_agent.ai_agent import is_available as _ai_is_available
except Exception:  # pragma: no cover - AI is optional
    _ai_is_available = None  # type: ignore[assignment]


def load_studio(config: AppConfig) -> dict[str, Any]:
    """Return the current Studio draft (or fall back to ``main.tex``)."""
    draft = _draft_path(config)
    source_path = draft if draft.exists() else _main_tex_path(config)
    text = ""
    origin = "empty"
    if source_path and source_path.exists():
        try:
            text = source_path.read_text(encoding="utf-8")
            origin = "draft" if source_path == draft else "main"
        except Exception:
            text = ""
    sections = list(_extract_section_titles(text))
    return {
        "text": text,
        "origin": origin,
        "draft_path": str(draft),
        "main_path": str(_main_tex_path(config) or ""),
        "sections": sections,
        "section_display": {s: section_display_name(s) for s in sections},
        "language": detect_cvlang(text),
        "compiler": available_latex_compiler() or "",
        "ai_available": _ai_is_available is not None and _ai_is_available(),
    }


def save_studio_draft(config: AppConfig, text: str) -> dict[str, Any]:
    """Write the user's working text to the Studio draft file."""
    draft = _draft_path(config)
    draft.write_text(text or "", encoding="utf-8")
    return {"ok": True, "draft_path": str(draft), "size": len(text or "")}


def reset_studio_draft(config: AppConfig) -> dict[str, Any]:
    """Delete the working draft so the next ``load`` falls back to main.tex."""
    draft = _draft_path(config)
    if draft.exists():
        draft.unlink()
    return {"ok": True}


def promote_draft_to_main(config: AppConfig) -> dict[str, Any]:
    """Copy the draft over the user's ``profiles/main.tex`` — validated.

    Hard guardrail: the draft must be a complete LaTeX CV document and must not
    be a suspicious shrink over an existing valid ``main.tex``. This is what
    prevents a placeholder/JSON/truncated draft from ever clobbering the real
    CV again (see ``validate_promote``). Every promote also snapshots the prior
    ``main.tex`` into ``profiles/.history`` for one-click restore.
    """
    draft = _draft_path(config)
    if not draft.exists():
        return {"ok": False, "reason": "no_draft"}
    if not config.profiles_dir:
        return {"ok": False, "reason": "no_profiles_dir"}
    main_path = Path(config.profiles_dir) / "main.tex"
    draft_text = draft.read_text(encoding="utf-8")
    ok, reason = validate_promote(draft_text, main_path if main_path.exists() else None)
    if not ok:
        return {"ok": False, "reason": reason, "log": _PROMOTE_REASONS.get(reason, reason)}
    if main_path.exists():
        # Versioned snapshot (reversible) + keep the legacy .bak for compatibility.
        snapshot_main_tex(config)
        backup = main_path.with_suffix(".bak")
        try:
            shutil.copyfile(main_path, backup)
        except Exception:
            pass
    shutil.copyfile(draft, main_path)
    return {"ok": True, "main_path": str(main_path)}


# User-readable explanations for promote rejections.
_PROMOTE_REASONS = {
    "not_latex_document": (
        "Refused: the draft is not a complete LaTeX CV (missing \\documentclass "
        "or \\begin{document}, or too short). Save-as-main only accepts a full "
        "CV document, never JSON/asset text or a placeholder."
    ),
    "suspicious_shrink": (
        "Refused: the draft is dramatically smaller than your current main.tex, "
        "which usually means a truncated or placeholder draft. Open your full CV "
        "in the editor before promoting, or restore a version from history."
    ),
}
