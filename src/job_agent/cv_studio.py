"""CV Studio — live editing helpers.

The Studio tab lets the user load their ``main.tex``, edit a draft directly in
the browser, compile it on demand, and pull AI suggestions. All work stays
local. The user's original ``profiles/main.tex`` is never modified unless they
explicitly click "Save as main.tex".

This module also supports:
- listing profile assets (main.tex, photo, .sty, .cls, .pdf, .json),
- reading / writing them safely (sandboxed to profiles/),
- replacing the photo with an upload,
- swapping the contact-icon pack (FontAwesome / academicons / text),
- importing a GitHub project into the CV's projects section,
- a single-page guard that trims content if the compiled PDF exceeds 1 page.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from job_agent.config import AppConfig
from job_agent.cv_studio_core import (
    _active_cv_text,
    _draft_path,
    _main_tex_path,
    _studio_dir,
    _write_draft,
    is_valid_latex_cv,
    list_main_versions,
    restore_main_version,
    snapshot_main_tex,
    validate_promote,
)
from job_agent.renderer.latex_render import (
    LatexCompileError,
    available_latex_compiler,
    compile_latex_to_pdf,
    copy_latex_assets,
    detect_cvlang,
    set_cvlang,
)
from job_agent.utils.html import strip_html

# Asset / icon-pack and project helpers live in sibling modules. Re-imported
# here so the historical public import paths
# (``from job_agent.cv_studio import list_assets, ICON_PACKS, save_project`` …)
# keep working unchanged.
from job_agent.cv_studio_assets import (  # noqa: F401  (public re-export seam)
    ICON_PACKS,
    apply_icon_pack,
    list_assets,
    read_asset,
    remove_photo,
    replace_photo,
    write_asset,
)
from job_agent.cv_studio_projects import (  # noqa: F401  (public re-export seam)
    import_github_project,
    save_project,
)

try:
    from job_agent.ai_agent import is_available as _ai_is_available
    from job_agent.ai_agent import _call_ollama_json as _ai_call_json  # type: ignore[attr-defined]
    from job_agent.polish import PolishOptions
except Exception:  # pragma: no cover - AI is optional
    _ai_is_available = None  # type: ignore[assignment]
    _ai_call_json = None  # type: ignore[assignment]
    PolishOptions = None  # type: ignore[assignment,misc]


# -----------------------------------------------------------------------------
# File I/O helpers — shared primitives now live in ``cv_studio_core``.
# -----------------------------------------------------------------------------


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


# -----------------------------------------------------------------------------
# Compile preview
# -----------------------------------------------------------------------------


def compile_preview(config: AppConfig, text: str | None = None) -> dict[str, Any]:
    """Compile the current draft to a PDF and return its path for preview."""
    studio = _studio_dir(config)
    tex_path = studio / "preview.tex"
    if text is not None:
        if not is_valid_latex_cv(text):
            return {
                "ok": False,
                "reason": "not_latex_document",
                "log": "Compile Preview only accepts a complete LaTeX CV draft (needs \\documentclass and \\begin{document}). Open JSON/assets in the asset editor, then keep main.tex in the main CV editor.",
            }
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
    "list_main_versions",
    "restore_main_version",
    "compile_preview",
    "suggest_edits",
    "reorder_sections",
    "section_display_name",
    "set_studio_language",
    "swap_studio_sections",
    "list_assets",
    "read_asset",
    "write_asset",
    "replace_photo",
    "remove_photo",
    "apply_icon_pack",
    "import_github_project",
    "single_page_guard",
]


# -----------------------------------------------------------------------------
# Single-page guard
# -----------------------------------------------------------------------------


def _count_pdf_pages(pdf_path: Path) -> int | None:
    """Cheap PDF page count: read the ``/Type /Page`` markers from the bytes.

    This avoids a hard dependency on pypdf. Good enough for moderncv output
    where the page tree is uncompressed.
    """
    try:
        data = pdf_path.read_bytes()
    except Exception:
        return None
    # Count /Type /Page (not /Pages) occurrences.
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")


def single_page_guard(config: AppConfig, text: str | None = None) -> dict[str, Any]:
    """Compile a draft and report whether it fits on one page.

    When it doesn't, we return a list of conservative trim suggestions the
    user can apply with one click (the actual trimming stays manual).
    """
    result = compile_preview(config, text)
    if not result.get("ok"):
        return {"ok": False, "reason": result.get("reason", "compile_failed"), "log": result.get("log", "")}
    pdf_path = Path(result["pdf_path"])
    page_count = _count_pdf_pages(pdf_path)
    if page_count is None:
        return {"ok": True, "page_count": None, "single_page": None, "trims": []}
    if page_count <= 1:
        return {"ok": True, "page_count": page_count, "single_page": True, "trims": []}
    # Build deterministic trim suggestions: tighten skills, drop oldest bullet,
    # trim summary to two sentences, drop second project.
    trims = [
        {
            "title": "Tighten summary to two sentences",
            "where": "\\newcommand{\\mysummary}{",
            "note": "Pick the two strongest sentences and delete the rest.",
        },
        {
            "title": "Drop the oldest job's least-relevant bullet",
            "where": "\\expthree",
            "note": "Keep technologies-line; remove one earlier bullet.",
        },
        {
            "title": "Limit Projects to your top one",
            "where": "\\projone",
            "note": "Keep the single most relevant project; remove the others.",
        },
        {
            "title": "Switch geometry margins to 0.85cm",
            "where": "\\usepackage{geometry}",
            "note": "Add \\usepackage[margin=0.85cm]{geometry} for an extra ~5 lines.",
        },
        {
            "title": "Switch font size to 10pt",
            "where": "\\documentclass[",
            "note": "Change 11pt to 10pt in the documentclass options.",
        },
    ]
    return {
        "ok": True,
        "page_count": page_count,
        "single_page": False,
        "trims": trims,
    }


def auto_fit_one_page(config: AppConfig, text: str) -> dict[str, Any]:
    """Apply conservative layout-only tightening to help a draft fit one page.

    The function never removes facts or rewrites content. It adjusts typography
    and spacing first, then returns the edited draft so the user can inspect it
    before saving/promoting.
    """
    if r"\begin{document}" not in (text or ""):
        return {"ok": False, "reason": "not_latex_document"}
    before = single_page_guard(config, text)
    if before.get("ok") and before.get("single_page") is True:
        return {"ok": True, "changed": False, "text": text, "page_count": before.get("page_count"), "steps": ["Already fits on one page."]}

    fitted = text
    steps: list[str] = []

    def _sub(pattern: str, replacement: str, label: str) -> None:
        nonlocal fitted
        new, count = re.subn(pattern, replacement, fitted, count=1)
        if count and new != fitted:
            fitted = new
            steps.append(label)

    _sub(r"\\documentclass\[11pt,", r"\\documentclass[10pt,", "Switched document class from 11pt to 10pt.")
    _sub(
        r"\\usepackage\[[^\]]*scale\s*=\s*0\.90[^\]]*\]\{geometry\}",
        r"\\usepackage[scale=0.93, top=0.95cm, bottom=0.95cm, left=1.35cm, right=1.35cm]{geometry}",
        "Tightened page margins while keeping readable white space.",
    )
    _sub(
        r"\\renewcommand\*?\{\\namefont\}\{\\fontsize\{26\}\{30\}",
        r"\\renewcommand*{\\namefont}{\\fontsize{24}{28}",
        "Reduced the name header slightly.",
    )
    _sub(r"\\photo\[(?:68|70|72)pt\]", r"\\photo[60pt]", "Reduced photo size slightly.")
    _sub(r"\\vspace\*\{-2\.0em\}", r"\\vspace*{-2.35em}", "Reduced vertical gap after the title.")

    after = single_page_guard(config, fitted)
    return {
        "ok": after.get("ok", False),
        "changed": bool(steps),
        "text": fitted,
        "page_count": after.get("page_count"),
        "single_page": after.get("single_page"),
        "steps": steps or ["No safe layout changes were found."],
        "log": after.get("log", ""),
    }


_ATS_ROLE_PACKS = {
    "data_scientist": [
        "Python", "SQL", "Machine Learning", "Statistics", "Predictive Modeling",
        "Feature Engineering", "Model Evaluation", "scikit-learn", "Pandas",
        "Time Series", "NLP", "Data Visualization",
    ],
    "ml_engineer": [
        "Python", "Deep Learning", "PyTorch", "TensorFlow", "Transformers",
        "Docker", "FastAPI", "MLOps", "Model Deployment", "CI/CD",
        "Experiment Tracking", "APIs",
    ],
    "data_engineer": [
        "Python", "SQL", "ETL", "Data Pipelines", "Spark", "Airflow",
        "APIs", "Docker", "Cloud", "Data Modeling", "Automation",
    ],
    "data_analyst": [
        "SQL", "Power BI", "Tableau", "Excel", "Statistics", "Dashboards",
        "Data Cleaning", "KPI", "Reporting", "Python", "Pandas",
    ],
}


def ats_keyword_radar(config: AppConfig, text: str, role: str = "data_scientist") -> dict[str, Any]:
    """Compare the current CV draft against a role-specific ATS keyword pack."""
    pack = _ATS_ROLE_PACKS.get(role) or _ATS_ROLE_PACKS["data_scientist"]
    haystack = (text or "").casefold()
    present = [kw for kw in pack if kw.casefold() in haystack]
    missing = [kw for kw in pack if kw.casefold() not in haystack]
    coverage = round((len(present) / max(1, len(pack))) * 100)
    suggestions = [
        {
            "keyword": kw,
            "where": "skills" if kw in {"Docker", "FastAPI", "MLOps", "Power BI", "Tableau", "Spark", "Airflow"} else "projects",
            "note": "Add only if true; recruiters reward evidence more than keyword stuffing.",
        }
        for kw in missing[:8]
    ]
    return {
        "ok": True,
        "role": role,
        "coverage": coverage,
        "present": present,
        "missing": missing,
        "suggestions": suggestions,
    }
