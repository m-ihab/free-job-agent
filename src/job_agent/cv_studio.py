"""CV Studio — live editing helpers.

The Studio tab lets the user load their ``main.tex``, edit a draft directly in
the browser, compile it on demand, and pull AI suggestions. All work stays
local. The user's original ``profiles/main.tex`` is never modified unless they
explicitly click "Save as main.tex".
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from job_agent.config import AppConfig
from job_agent.renderer.latex_render import (
    LatexCompileError,
    available_latex_compiler,
    compile_latex_to_pdf,
    copy_latex_assets,
)
from job_agent.utils.html import strip_html

try:
    from job_agent.ai_agent import is_available as _ai_is_available
    from job_agent.ai_agent import _call_ollama_json as _ai_call_json  # type: ignore[attr-defined]
    from job_agent.polish import PolishOptions
except Exception:  # pragma: no cover - AI is optional
    _ai_is_available = None  # type: ignore[assignment]
    _ai_call_json = None  # type: ignore[assignment]
    PolishOptions = None  # type: ignore[assignment]


STUDIO_DIRNAME = "cv_studio"


# -----------------------------------------------------------------------------
# File I/O helpers
# -----------------------------------------------------------------------------


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
    """Copy the draft over the user's ``profiles/main.tex`` (with backup)."""
    draft = _draft_path(config)
    if not draft.exists():
        return {"ok": False, "reason": "no_draft"}
    if not config.profiles_dir:
        return {"ok": False, "reason": "no_profiles_dir"}
    main_path = Path(config.profiles_dir) / "main.tex"
    if main_path.exists():
        backup = main_path.with_suffix(".bak")
        try:
            shutil.copyfile(main_path, backup)
        except Exception:
            pass
    shutil.copyfile(draft, main_path)
    return {"ok": True, "main_path": str(main_path)}


# -----------------------------------------------------------------------------
# Compile preview
# -----------------------------------------------------------------------------


def compile_preview(config: AppConfig, text: str | None = None) -> dict[str, Any]:
    """Compile the current draft to a PDF and return its path for preview."""
    studio = _studio_dir(config)
    tex_path = studio / "preview.tex"
    if text is not None:
        tex_path.write_text(text, encoding="utf-8")
    elif _draft_path(config).exists():
        shutil.copyfile(_draft_path(config), tex_path)
    elif _main_tex_path(config):
        shutil.copyfile(_main_tex_path(config), tex_path)  # type: ignore[arg-type]
    else:
        return {"ok": False, "reason": "no_source"}
    # Make sure assets are next to the tex file (photo + .sty + .cls).
    copy_latex_assets(config.profiles_dir, studio)
    pdf_path = studio / "preview.pdf"
    try:
        compile_latex_to_pdf(tex_path, pdf_path)
    except LatexCompileError as exc:
        return {"ok": False, "reason": "compile_failed", "log": str(exc)[-4000:]}
    return {"ok": True, "pdf_path": str(pdf_path)}


# -----------------------------------------------------------------------------
# Section extraction (for the drag-and-drop reorder UI)
# -----------------------------------------------------------------------------


def _extract_section_titles(text: str) -> list[str]:
    titles: list[str] = []
    if not text:
        return titles
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(r"\section{"):
            inner = line[len(r"\section{"):].rstrip("}").strip()
            if inner.startswith("\\"):
                inner = inner.lstrip("\\").rstrip("}")
            titles.append(inner or "(section)")
    return titles


# -----------------------------------------------------------------------------
# AI suggestions
# -----------------------------------------------------------------------------


_SUGGEST_PROMPT = """You review a LaTeX CV draft for a Paris data/AI candidate
applying to a specific job. Return JSON only:

{
  "suggestions": [
    {
      "title": "short label",
      "section": "summary|skills|experience|projects|education|other",
      "priority": "high|medium|low",
      "rationale": "one sentence",
      "before": "exact excerpt the user has now (<= 200 chars) or empty",
      "after": "rewrite proposal (<= 220 chars) or empty"
    }
  ]
}

Rules:
- Never invent dates, metrics, companies, sponsorship claims, or facts.
- 3-6 suggestions max. Skip if the CV is already great.
- "before" must be an exact substring of the source if non-empty.
- Tone: professional, concise, role-aware.

CV (truncated to 12000 chars):
{cv}

JOB CONTEXT (may be empty):
{job}

JSON:"""


def suggest_edits(
    cv_text: str,
    job_context: str = "",
    *,
    options: "PolishOptions | None" = None,
) -> dict[str, Any]:
    """Ask the local AI for concrete CV edit suggestions."""
    if _ai_is_available is None or _ai_call_json is None or PolishOptions is None:
        return {"available": False, "suggestions": []}
    opts = options or PolishOptions.from_env()
    if not _ai_is_available(opts):
        return {"available": False, "suggestions": []}
    prompt = (
        _SUGGEST_PROMPT
        .replace("{cv}", strip_html(cv_text or "")[:12000])
        .replace("{job}", strip_html(job_context or "")[:1500])
    )
    raw = _ai_call_json(prompt, opts)
    if not isinstance(raw, dict):
        return {"available": True, "suggestions": []}
    suggestions: list[dict[str, Any]] = []
    for item in (raw.get("suggestions") or [])[:8]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:80]
        if not title:
            continue
        suggestions.append({
            "title": title,
            "section": str(item.get("section") or "other").strip().lower(),
            "priority": str(item.get("priority") or "medium").strip().lower(),
            "rationale": str(item.get("rationale") or "").strip()[:240],
            "before": str(item.get("before") or "").strip()[:600],
            "after": str(item.get("after") or "").strip()[:600],
        })
    return {"available": True, "suggestions": suggestions}


# -----------------------------------------------------------------------------
# Section reorder
# -----------------------------------------------------------------------------


def reorder_sections(text: str, order: list[str]) -> str:
    """Reorder ``\\section{...}`` blocks inside the document body.

    ``order`` is a list of section labels (matching what ``_extract_section_titles``
    returned). Sections not mentioned in ``order`` keep their relative order
    and come after the reordered ones.
    """
    if not text or not order:
        return text
    begin = text.find(r"\begin{document}")
    end = text.find(r"\end{document}", begin if begin >= 0 else 0)
    if begin < 0 or end < 0 or end <= begin:
        return text
    preamble = text[: begin + len(r"\begin{document}")]
    body = text[begin + len(r"\begin{document}") : end]
    closing = text[end:]

    # Split body into (header, blocks) where each block starts with \section{...}.
    blocks: list[tuple[str, str]] = []  # (title, raw_block)
    header_lines: list[str] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(r"\section{"):
            if current_title is None:
                # First section: previous lines belong to the header.
                pass
            else:
                blocks.append((current_title, "".join(current_lines)))
            current_title = stripped[len(r"\section{"):].rstrip("}").strip().lstrip("\\")
            current_lines = [line]
        else:
            if current_title is None:
                header_lines.append(line)
            else:
                current_lines.append(line)
    if current_title is not None:
        blocks.append((current_title, "".join(current_lines)))

    if not blocks:
        return text

    title_to_block = {title: raw for title, raw in blocks}
    remaining = [title for title, _ in blocks]
    reordered: list[str] = []
    for label in order:
        # Tolerant match: case-insensitive, ignore wrapping braces.
        match = next(
            (title for title in remaining if title.casefold() == label.casefold()),
            None,
        )
        if match is not None:
            reordered.append(title_to_block[match])
            remaining.remove(match)
    for title in remaining:
        reordered.append(title_to_block[title])

    new_body = "".join(header_lines) + "".join(reordered)
    return preamble + new_body + closing


__all__ = [
    "load_studio",
    "save_studio_draft",
    "reset_studio_draft",
    "promote_draft_to_main",
    "compile_preview",
    "suggest_edits",
    "reorder_sections",
]
