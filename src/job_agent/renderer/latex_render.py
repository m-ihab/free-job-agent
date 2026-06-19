"""Render tailored CV content to LaTeX and optionally compile it.

The strategy is conservative: when the user provides a master ``main.tex``, the
renderer preserves its curated design, narrative, and styling. It only swaps in
role-specific text where it materially helps the application:

- ``\\mysummary``: keep the master text and add a short closing sentence that
  names the target role/company and the top matching skills.
- ``\\expone/\\exptwo/\\expthree``: re-rank bullets by relevance to the job so
  the most relevant points appear first. Bullets are not invented.
- ``\\projone`` (and ``projtwo``/``projthree`` if present): pick the most
  relevant project from ``master_cv.json``.
- Skills, education, languages, and other curated narrative blocks stay as the
  user wrote them in ``main.tex`` so the CV reads naturally.

Both the English and French branches of an ``\\ifthenelse{\\equal{\\cvlang}{en}}``
block are tailored consistently.

The pure text / escaping / section-rendering helpers live in
:mod:`job_agent.renderer.latex_helpers` and are re-exported here so existing
import paths (``from job_agent.renderer.latex_render import _tailored_summary``
etc.) keep working unchanged.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.schemas.job import JobListing
from job_agent.renderer.latex_helpers import (
    _cap_itemize_items,
    _escape_latex,
    _experience_body,
    _github_handle,
    _has_command,
    _inline_latex,
    _is_french,
    _iter_newcommand_bodies,
    _keyword_score,
    _linkedin_handle,
    _project_body,
    _replace_line_command,
    _replace_newcommand_body,
    _replace_newcommand_branch_bodies,
    _tailored_summary,
)

# Re-exported for callers/tests that import these private helpers from this
# module's historical path (``from job_agent.renderer.latex_render import ...``).
from job_agent.renderer.latex_helpers import (  # noqa: F401  (re-export seam)
    _clean_role_phrase,
    _detect_contract_family,
)

try:
    from job_agent.ai_agent import generate_tailored_summary as _ai_generate_summary
except Exception:  # pragma: no cover
    def _ai_generate_summary(*args, **kwargs):  # type: ignore[misc]
        return None


class LatexCompileError(RuntimeError):
    """Raised when a LaTeX compiler exists but cannot build the PDF."""


def set_cvlang(source: str, language: str | None) -> str:
    """Force the moderncv ``\\cvlang`` toggle to ``en`` or ``fr``.

    The bundled ``main.tex`` defines ``\\newcommand{\\cvlang}{en}`` and carries
    full English + French content branches, so switching languages is a
    one-line rewrite — no translation required. Unknown or empty languages, or
    a template without the toggle, leave the source untouched.
    """
    if not language:
        return source
    lang = language.strip().lower()
    if lang not in {"en", "fr"} or r"\cvlang" not in source:
        return source
    new_source, replaced = re.subn(
        r"\\(?:re)?newcommand\s*\{\\cvlang\}\s*\{[^}]*\}",
        rf"\\newcommand{{\\cvlang}}{{{lang}}}",
        source,
        count=1,
    )
    if not replaced:
        return source
    # Drop any leftover commented toggle line so it can't confuse a later edit.
    new_source = re.sub(
        r"(?m)^\s*%\s*\\(?:re)?newcommand\s*\{\\cvlang\}\s*\{[^}]*\}\s*$\n?",
        "",
        new_source,
    )
    return new_source


def detect_cvlang(source: str) -> str:
    """Return the active ``\\cvlang`` value (``en``/``fr``); defaults to ``en``."""
    match = re.search(r"(?<!%)\\(?:re)?newcommand\s*\{\\cvlang\}\s*\{\s*(en|fr)\s*\}", source or "")
    return match.group(1).lower() if match else "en"


def count_pdf_pages(pdf_path: Path) -> int | None:
    """Cheap PDF page count via ``/Type /Page`` markers (no pypdf dependency)."""
    try:
        data = pdf_path.read_bytes()
    except Exception:
        return None
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")


def compact_cv_source(source: str, level: int) -> str:
    """Tighten a moderncv source so a slightly-overflowing CV fits one page.

    Level 1 is typography-only (no content removed): smaller base font and
    tighter margins. Level 2 additionally caps each bullet list to its top 3
    items — a factual trim that keeps the strongest bullets. Used only after a
    compile shows the tailored CV spilled onto a second page.
    """
    out = source
    if level >= 1:
        out = re.sub(r"(\\documentclass\[[^\]]*?)11pt", r"\g<1>10pt", out, count=1)
        out = re.sub(r"top=1\.2cm,\s*bottom=1\.2cm", "top=0.8cm, bottom=0.8cm", out)
        out = re.sub(r"scale=0\.90", "scale=0.93", out)
    if level >= 2:
        out = re.sub(
            r"\\begin\{itemize\}.*?\\end\{itemize\}",
            lambda m: _cap_itemize_items(m.group(0), 3),
            out,
            flags=re.S,
        )
    return out


def render_moderncv_template(
    template_path: Path,
    *,
    job: JobListing,
    master_cv: MasterCV,
    profile: CandidateProfile,
    language: str | None = None,
) -> str:
    """Render a tailored CV by preserving the user's moderncv template.

    Only role-specific text is rewritten. The master template's design,
    section ordering, language toggle, photo, font, and curated narrative
    skill blocks stay intact. When ``language`` is ``en``/``fr`` the
    ``\\cvlang`` toggle is set accordingly; otherwise the template's own value
    is preserved.
    """
    source = template_path.read_text(encoding="utf-8")
    header_comment = "% Tailored by free-job-agent for " + _inline_latex(f"{job.title} at {job.company}") + "\n"
    source = header_comment + source
    # Widen hint column so labels like "Cloud/Platforms", "Programming",
    # "BI/Tools" don't overlap with the skill text. We only adjust if the
    # master is at the moderncv default (2.3cm) — bespoke values are kept.
    source = re.sub(
        r"\\setlength\{\\hintscolumnwidth\}\{2\.3cm\}",
        r"\\setlength{\\hintscolumnwidth}{2.85cm}",
        source,
    )

    contact = master_cv.contact
    names = contact.name.split()
    first_name = names[0] if names else contact.name
    last_name = " ".join(names[1:]) if len(names) > 1 else ""

    source = _replace_line_command(source, r"^\\name\{.*?\}\{.*?\}$", rf"\name{{{_inline_latex(first_name)}}}{{{_inline_latex(last_name)}}}")
    source = _replace_line_command(source, r"^\\address\{.*?\}\{.*?\}\{.*?\}$", rf"\address{{{_inline_latex(contact.location or '')}}}{{}}{{}}")
    source = _replace_line_command(source, r"^\\phone\[mobile\]\{.*?\}$", rf"\phone[mobile]{{{_inline_latex(contact.phone or '')}}}")
    source = _replace_line_command(source, r"^\\email\{.*?\}$", rf"\email{{{_inline_latex(contact.email)}}}")
    if contact.linkedin_url:
        source = _replace_line_command(
            source,
            r"^\\social\[linkedin\]\{.*?\}$",
            rf"\social[linkedin]{{{_inline_latex(_linkedin_handle(contact.linkedin_url))}}}",
        )
    if contact.github_url:
        github_command = rf"\social[github]{{{_inline_latex(_github_handle(contact.github_url))}}}"
        if re.search(r"^%?\s*\\social\[github\]\{.*?\}$", source, flags=re.MULTILINE):
            source = _replace_line_command(source, r"^%?\s*\\social\[github\]\{.*?\}$", github_command)
        else:
            source = source.replace(r"\social[linkedin]", github_command + "\n" + r"\social[linkedin]", 1)

    # Summary: keep curated narrative, add one closing sentence.
    summary_branches = list(_iter_newcommand_bodies(source, "mysummary"))
    if summary_branches:
        new_summaries: list[str] = []
        for _, _, body in summary_branches:
            french = _is_french(body)
            new_summaries.append(_tailored_summary(job, master_cv, profile, original_body=body, french=french))
        source = _replace_newcommand_branch_bodies(source, "mysummary", new_summaries)

    # Experience: only rewrite if master_cv.json has data; otherwise keep original.
    for command_name, experience in zip(
        ["expone", "exptwo", "expthree", "expfour", "expfive"], master_cv.experience, strict=False
    ):
        if _has_command(source, command_name):
            source = _replace_newcommand_body(source, command_name, _experience_body(experience, job))

    # Projects: rank ALL projects, then fill projone/projtwo/projthree if the
    # template defines them. If the template only has projone (the common
    # case for the bundled main.tex), pack the top 3 projects into projone
    # so the user doesn't lose project visibility on a one-page CV.
    if master_cv.projects:
        ranked_projects = sorted(
            master_cv.projects,
            key=lambda project: _keyword_score(project.description + " " + " ".join(project.technologies) + " " + project.name, job),
            reverse=True,
        )
        defined_slots = [name for name in ("projone", "projtwo", "projthree") if _has_command(source, name)]
        if defined_slots:
            if len(defined_slots) == 1:
                # Single slot: render top 3 projects stacked inside it.
                blocks = [_project_body(project, job) for project in ranked_projects[:3]]
                source = _replace_newcommand_body(source, defined_slots[0], "\n".join(blocks))
            else:
                # Multiple slots: one per slot.
                for command_name, project in zip(defined_slots, ranked_projects, strict=False):
                    source = _replace_newcommand_body(source, command_name, _project_body(project, job))

    source = set_cvlang(source, language)
    return source


def render_latex_source(
    markdown_content: str,
    title: str = "Tailored CV",
    *,
    template_path: Path | None = None,
    job: JobListing | None = None,
    master_cv: MasterCV | None = None,
    profile: CandidateProfile | None = None,
    language: str | None = None,
) -> str:
    """Convert the generated CV markdown into editable LaTeX source.

    When a ``main.tex`` template is provided alongside the job and profile
    data, ``render_moderncv_template`` is used so the CV preserves the user's
    curated design and only role-relevant text is updated. Otherwise this
    falls back to a minimal article-class document built from the Markdown so
    the workflow still produces a valid ``cv.tex`` and PDF.
    """
    if template_path and template_path.exists() and job and master_cv and profile:
        return render_moderncv_template(template_path, job=job, master_cv=master_cv, profile=profile, language=language)

    body: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            body.append(r"\end{itemize}")
            in_list = False

    for raw_line in markdown_content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("<!--"):
            close_list()
            if body and body[-1] != "":
                body.append("")
            continue
        if line.startswith("# "):
            close_list()
            body.append(rf"\begin{{center}}\LARGE\textbf{{{_inline_latex(line[2:])}}}\end{{center}}")
        elif line.startswith("## "):
            close_list()
            body.append(rf"\section*{{{_inline_latex(line[3:])}}}")
        elif line.startswith("### "):
            close_list()
            body.append(rf"\subsection*{{{_inline_latex(line[4:])}}}")
        elif re.match(r"^[-*]\s+", line):
            if not in_list:
                body.append(r"\begin{itemize}")
                in_list = True
            item_text = re.sub(r"^[-*]\s+", "", line)
            body.append(rf"\item {_inline_latex(item_text)}")
        else:
            close_list()
            body.append(_inline_latex(line) + r"\\")
    close_list()

    return "\n".join(
        [
            r"\documentclass[11pt,a4paper]{article}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage[margin=1.45cm]{geometry}",
            r"\usepackage[hidelinks]{hyperref}",
            r"\usepackage{enumitem}",
            r"\setlist[itemize]{leftmargin=*, itemsep=0.15em, topsep=0.2em}",
            r"\setlength{\parindent}{0pt}",
            r"\setlength{\parskip}{0.35em}",
            rf"\title{{{_escape_latex(title)}}}",
            r"\date{}",
            r"\begin{document}",
            *body,
            r"\end{document}",
            "",
        ]
    )


def copy_latex_assets(source_dir: Path | str | None, output_dir: Path | str) -> list[Path]:
    """Copy local LaTeX assets such as photos and style files beside cv.tex."""
    if source_dir is None:
        return []
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    copied: list[Path] = []
    for pattern in ["*.jpg", "*.jpeg", "*.png", "*.sty", "*.cls"]:
        for source in source_dir.glob(pattern):
            destination = output_dir / source.name
            if source.resolve() == destination.resolve():
                continue
            shutil.copyfile(source, destination)
            copied.append(destination)
    return copied


def _safe_existing_file(path: Path) -> bool:
    try:
        return path.exists() and path.is_file()
    except OSError:
        return False


def _perl_available() -> bool:
    """latexmk needs a Perl interpreter; check before preferring it."""
    return shutil.which("perl") is not None


def available_latex_compiler() -> str | None:
    """Return the best available LaTeX compiler executable.

    Preference order:
    - latexmk (preferred — handles reruns/cross-refs/bibliography cleanly)
      but only when Perl is on PATH, since MiKTeX latexmk needs it.
    - pdflatex / xelatex / lualatex as direct fallbacks (no Perl needed).

    The order can be overridden by ``JOB_AGENT_LATEX_COMPILER``.
    """
    configured = os.environ.get("JOB_AGENT_LATEX_COMPILER", "").strip()
    if configured:
        configured_path = Path(configured)
        if _safe_existing_file(configured_path):
            return str(configured_path)
        found_configured = shutil.which(configured)
        if found_configured:
            return found_configured

    has_perl = _perl_available()
    order = (
        ["latexmk", "pdflatex", "xelatex", "lualatex"]
        if has_perl
        else ["pdflatex", "xelatex", "lualatex", "latexmk"]
    )
    for command in order:
        found = shutil.which(command)
        if found:
            return found
    common_roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64",
        Path(os.environ.get("PROGRAMFILES", "")) / "MiKTeX" / "miktex" / "bin" / "x64",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "MiKTeX" / "miktex" / "bin" / "x64",
        Path(os.environ.get("APPDATA", "")) / "TinyTeX" / "bin" / "windows",
        Path(os.environ.get("APPDATA", "")) / "TinyTeX" / "bin" / "win32",
    ]
    fallback_order = (
        ["latexmk.exe", "pdflatex.exe", "xelatex.exe", "lualatex.exe"]
        if has_perl
        else ["pdflatex.exe", "xelatex.exe", "lualatex.exe", "latexmk.exe"]
    )
    for root in common_roots:
        if not str(root):
            continue
        for command in fallback_order:
            candidate = root / command
            if _safe_existing_file(candidate):
                return str(candidate)
    return None


def _latex_subprocess_env() -> dict[str, str]:
    """Return an env that lets MiKTeX latexmk find Strawberry Perl."""
    env = os.environ.copy()
    path_parts = env.get("PATH", "").split(os.pathsep)
    for candidate in [Path("C:/Strawberry/perl/bin"), Path("C:/Perl64/bin"), Path("C:/Perl/bin")]:
        if candidate.exists():
            candidate_str = str(candidate)
            if not any(part.casefold() == candidate_str.casefold() for part in path_parts):
                path_parts.insert(0, candidate_str)
    env["PATH"] = os.pathsep.join(path_parts)
    return env


def compile_latex_to_pdf(tex_path: Path | str, output_pdf: Path | str) -> Path:
    """Compile a LaTeX file to PDF using a local compiler."""
    tex_path = Path(tex_path)
    output_pdf = Path(output_pdf)
    compiler = available_latex_compiler()
    if compiler is None:
        raise LatexCompileError("No LaTeX compiler found on PATH. Install MiKTeX or TeX Live to build cv.pdf from cv.tex.")

    workdir = tex_path.parent
    if Path(compiler).name.lower().startswith("latexmk"):
        command = [compiler, "-pdf", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    else:
        command = [compiler, "-interaction=nonstopmode", "-halt-on-error", tex_path.name]

    last_result: subprocess.CompletedProcess[str] | None = None
    for _ in range(2):
        try:
            last_result = subprocess.run(
                command,
                cwd=workdir,
                env=_latex_subprocess_env(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise LatexCompileError(
                "LaTeX compilation timed out after 120 seconds. "
                "A reportlab fallback PDF will be used instead."
            ) from exc
        if last_result.returncode != 0:
            break

    built_pdf = tex_path.with_suffix(".pdf")
    if last_result is None or last_result.returncode != 0 or not built_pdf.exists():
        output = last_result.stdout if last_result else ""
        raise LatexCompileError(output[-4000:] or "LaTeX compilation failed without output.")

    if built_pdf.resolve() != output_pdf.resolve():
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built_pdf, output_pdf)
    # Clean up latexmk's intermediate files. We keep cv.log for debugging.
    for stale in ("cv.aux", "cv.out", "cv.fdb_latexmk", "cv.fls"):
        try:
            (workdir / stale).unlink(missing_ok=True)
        except Exception:
            pass
    return output_pdf
