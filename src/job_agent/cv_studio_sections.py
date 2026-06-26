"""CV Studio — section extraction, display names, language toggle, reorder."""
from __future__ import annotations

from typing import Any

from job_agent.config import AppConfig
from job_agent.cv_studio_core import _active_cv_text, _draft_path, _write_draft
from job_agent.renderer.latex_render import detect_cvlang, set_cvlang


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


# moderncv templates reference sections by command (\section{\sectedu}); map the
# command tokens to human labels for the reorder UI. Unknown tokens echo back.
_SECTION_DISPLAY = {
    "sectsummary": "Profile",
    "sectedu": "Education",
    "sectexp": "Professional Experience",
    "sectproj": "Projects",
    "sectskills": "Technical Skills",
    "sectlang": "Languages",
}


def section_display_name(label: str) -> str:
    """Return a human-friendly name for a raw section label/command token."""
    key = (label or "").strip().lstrip("\\").casefold()
    if key in _SECTION_DISPLAY:
        return _SECTION_DISPLAY[key]
    # Title-case a plain literal section title, leave real words intact.
    return (label or "").strip() or "(section)"


def set_studio_language(config: AppConfig, language: str) -> dict[str, Any]:
    """Switch the active draft between English and French via ``\\cvlang``.

    Writes the result to the working draft (never to main.tex) so the change is
    reversible and previewable. Returns the new detected language.
    """
    lang = (language or "").strip().lower()
    if lang not in {"en", "fr"}:
        return {"ok": False, "reason": "bad_language", "language": ""}
    text, _, _ = _active_cv_text(config)
    if not text or r"\cvlang" not in text:
        return {"ok": False, "reason": "no_language_toggle", "language": detect_cvlang(text)}
    updated = set_cvlang(text, lang)
    _write_draft(config, updated)
    return {"ok": True, "language": detect_cvlang(updated), "text": updated, "draft_path": str(_draft_path(config))}


def swap_studio_sections(config: AppConfig, label_a: str, label_b: str) -> dict[str, Any]:
    """Swap the position of two sections in the active draft and save it.

    Matching is tolerant: it accepts raw command tokens (``sectedu``) or human
    labels (``Education``). Only the order changes — section content is never
    edited. The result is written to the working draft.
    """
    text, _, _ = _active_cv_text(config)
    titles = _extract_section_titles(text)
    if not titles:
        return {"ok": False, "reason": "no_sections", "sections": []}

    def _resolve(token: str) -> str | None:
        token_cf = (token or "").strip().lstrip("\\").casefold()
        for title in titles:
            if title.casefold() == token_cf:
                return title
            if section_display_name(title).casefold() == token_cf:
                return title
        return None

    first = _resolve(label_a)
    second = _resolve(label_b)
    if not first or not second or first == second:
        return {"ok": False, "reason": "section_not_found", "sections": titles}
    order = list(titles)
    i, j = order.index(first), order.index(second)
    order[i], order[j] = order[j], order[i]
    updated = reorder_sections(text, order)
    _write_draft(config, updated)
    new_titles = _extract_section_titles(updated)
    return {
        "ok": True,
        "text": updated,
        "sections": new_titles,
        "section_display": {s: section_display_name(s) for s in new_titles},
        "draft_path": str(_draft_path(config)),
    }


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
