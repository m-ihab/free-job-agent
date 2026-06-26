"""CV Studio — compile preview, page-count guard, and one-page auto-fit.

The LaTeX collaborators ``copy_latex_assets`` and ``compile_latex_to_pdf`` are
reached through the :mod:`job_agent.cv_studio` module object (``cs.<name>``) so
the studio tests' ``monkeypatch.setattr(cv_studio, ...)`` seams keep working
after the split.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import job_agent.cv_studio as cs
from job_agent.config import AppConfig
from job_agent.cv_studio_core import (
    _draft_path,
    _main_tex_path,
    _studio_dir,
    is_valid_latex_cv,
)
from job_agent.renderer.latex_render import LatexCompileError


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
    cs.copy_latex_assets(config.profiles_dir, studio)
    pdf_path = studio / "preview.pdf"
    try:
        cs.compile_latex_to_pdf(tex_path, pdf_path)
    except LatexCompileError as exc:
        return {"ok": False, "reason": "compile_failed", "log": str(exc)[-4000:]}
    return {"ok": True, "pdf_path": str(pdf_path)}


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
