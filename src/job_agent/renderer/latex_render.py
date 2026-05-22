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
"""
from __future__ import annotations

from calendar import month_name
import os
import re
import shutil
import subprocess
from pathlib import Path

from job_agent.schemas.candidate import CandidateProfile, MasterCV, Project, Skill, WorkExperience
from job_agent.schemas.job import JobListing

try:
    from job_agent.ai_agent import generate_tailored_summary as _ai_generate_summary
except Exception:  # pragma: no cover
    def _ai_generate_summary(*args, **kwargs):  # type: ignore[misc]
        return None


class LatexCompileError(RuntimeError):
    """Raised when a LaTeX compiler exists but cannot build the PDF."""


_FRENCH_HINT_RE = re.compile(r"[éèêëàâäîïôöùûüç]|stage|alternance|stagiaire", re.IGNORECASE)


def _escape_latex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _inline_latex(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    escaped = _escape_latex(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\\textit{\1}", escaped)
    return escaped


def _keyword_score(text: str, job: JobListing) -> int:
    keywords = job.tech_stack + job.requirements + job.responsibilities + [job.title]
    text_lower = text.casefold()
    score = 0
    for keyword in keywords:
        keyword = keyword.casefold().strip()
        if keyword and keyword in text_lower:
            score += 3
    return score


def _rank_texts(values: list[str], job: JobListing, limit: int | None = None) -> list[str]:
    ranked = sorted(values, key=lambda value: _keyword_score(value, job), reverse=True)
    return ranked[:limit] if limit is not None else ranked


def _format_date(value: str | None) -> str:
    if not value:
        return "Present"
    match = re.match(r"^(\d{4})-(\d{2})$", value)
    if match:
        year, month = match.groups()
        return f"{month_name[int(month)]} {year}"
    return value


def _date_range(start: str | None, end: str | None) -> str:
    return f"{_format_date(start)} -- {_format_date(end)}"


def _latex_itemize(items: list[str]) -> str:
    if not items:
        return ""
    lines = [r"\begin{itemize}"]
    lines.extend(rf"            \item {_inline_latex(item)}" for item in items)
    lines.append(r"        \end{itemize}")
    return "\n".join(lines)


def _cventry(date: str, title: str, org: str, location: str, details: str) -> str:
    return "\n".join(
        [
            rf"        \cventry{{{_inline_latex(date)}}}{{{_inline_latex(title)}}}{{{_inline_latex(org)}}}{{{_inline_latex(location)}}}{{}}{{",
            details,
            r"        }",
        ]
    )


def _experience_body(exp: WorkExperience, job: JobListing) -> str:
    bullets = _rank_texts(exp.bullet_points, job, limit=4)
    if exp.technologies:
        bullets.append("Technologies: " + ", ".join(exp.technologies))
    return _cventry(_date_range(exp.start_date, exp.end_date), exp.title, exp.company, exp.location or "", _latex_itemize(bullets))


def _project_body(project: Project, job: JobListing) -> str:
    bullets = _rank_texts(project.bullet_points, job, limit=1)
    detail_parts = [project.description] + bullets
    detail = " ".join(part for part in detail_parts if part)
    if project.technologies:
        detail += " Technologies: " + ", ".join(project.technologies)
    return rf"\cvitem{{\textbf{{{_inline_latex(project.name)}}}}}{{{_inline_latex(detail)}}}"


def _skill_score(skill: Skill, job: JobListing) -> int:
    return _keyword_score(skill.name, job)


def _job_focus_terms(job: JobListing, master_cv: MasterCV, limit: int = 4) -> list[str]:
    """Pick the top skills/tech that overlap between the job and the candidate."""
    job_text = " ".join(job.tech_stack + job.requirements + job.responsibilities + [job.title]).casefold()
    terms: list[str] = []
    seen: set[str] = set()
    for skill in sorted(master_cv.skills, key=lambda s: _skill_score(s, job), reverse=True):
        name = skill.name.strip()
        key = name.casefold()
        if name and key in job_text and key not in seen:
            terms.append(name)
            seen.add(key)
        if len(terms) >= limit:
            break
    if len(terms) < limit:
        for raw in job.tech_stack + job.requirements:
            cleaned = raw.strip(" .,:;")
            key = cleaned.casefold()
            if 2 <= len(cleaned) <= 40 and key not in seen:
                terms.append(cleaned)
                seen.add(key)
            if len(terms) >= limit:
                break
    return terms


def _is_french(text: str) -> bool:
    return bool(text and _FRENCH_HINT_RE.search(text))


def _tailored_summary(
    job: JobListing,
    master_cv: MasterCV,
    profile: CandidateProfile,
    *,
    original_body: str,
    french: bool,
) -> str:
    """Return a tailored summary that preserves the master narrative.

    Returns a string of valid LaTeX. The curated body is preserved verbatim so
    existing escapes like ``\\&`` stay intact, and only the appended closing
    sentence (plain text from job/profile data) is LaTeX-escaped.
    """
    body = original_body.strip()
    if not body:
        body = _escape_latex((profile.summary or master_cv.summary or "").strip())
    body = re.sub(r"\s+", " ", body).strip()
    base = body[:-1] if body.endswith(".") else body
    focus = _job_focus_terms(job, master_cv, limit=4)
    role = job.title.strip() if job.title else ""
    company = job.company.strip() if job.company else ""
    if not (role and company):
        return base + "."
    if french:
        tail = f" Candidature ciblée pour le poste de {role} chez {company}"
        if focus:
            tail += f", avec un accent sur {', '.join(focus)}"
    else:
        tail = f" Targeting the {role} role at {company}"
        if focus:
            tail += f", with strong emphasis on {', '.join(focus)}"
    tail += "."
    return base + "." + _escape_latex(tail)


def _replace_newcommand_body(source: str, command_name: str, body: str) -> str:
    """Replace the body of the first occurrence of ``\\newcommand{\\command_name}``.

    Only the first occurrence is replaced. The user's ``main.tex`` typically
    defines content commands twice — once in the English ``\\ifthenelse``
    branch, once in the French branch — and the French branch should keep its
    curated translation. To update both branches with different bodies, use
    ``_replace_newcommand_branch_bodies``.
    """
    marker = rf"\newcommand{{\{command_name}}}"
    marker_start = source.find(marker)
    if marker_start < 0:
        return source
    body_start = source.find("{", marker_start + len(marker))
    if body_start < 0:
        return source

    depth = 0
    index = body_start
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[: body_start + 1] + "\n" + body.rstrip() + "\n    " + source[index:]
        index += 1
    return source


def _iter_newcommand_bodies(source: str, command_name: str):
    """Yield ``(start, end, body)`` for every occurrence of the named command."""
    pattern_prefix = rf"\newcommand{{\{command_name}}}"
    cursor = 0
    while True:
        marker_start = source.find(pattern_prefix, cursor)
        if marker_start < 0:
            return
        body_start = source.find("{", marker_start + len(pattern_prefix))
        if body_start < 0:
            return
        depth = 0
        index = body_start
        while index < len(source):
            char = source[index]
            if char == "\\":
                index += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    body = source[body_start + 1 : index]
                    yield (body_start + 1, index, body)
                    cursor = index + 1
                    break
            index += 1
        else:
            return


def _replace_newcommand_branch_bodies(source: str, command_name: str, new_bodies: list[str]) -> str:
    """Replace each occurrence of a command with the body at the same index.

    If there are more occurrences than provided bodies, the last body is
    reused. If a body is empty, the original is kept untouched.
    """
    if not new_bodies:
        return source
    positions = list(_iter_newcommand_bodies(source, command_name))
    if not positions:
        return source
    result_parts: list[str] = []
    cursor = 0
    for index, (start, end, _) in enumerate(positions):
        body_index = min(index, len(new_bodies) - 1)
        body = new_bodies[body_index]
        if not body.strip():
            continue
        result_parts.append(source[cursor:start])
        result_parts.append("\n" + body.rstrip() + "\n    ")
        cursor = end
    result_parts.append(source[cursor:])
    return "".join(result_parts)


def _replace_line_command(source: str, pattern: str, replacement: str) -> str:
    return re.sub(pattern, lambda _: replacement, source, count=1, flags=re.MULTILINE)


def _linkedin_handle(url: str | None) -> str:
    if not url:
        return ""
    cleaned = url.rstrip("/")
    if "/in/" in cleaned:
        return cleaned.rsplit("/in/", 1)[1]
    return cleaned.rsplit("/", 1)[-1]


def _github_handle(url: str | None) -> str:
    if not url:
        return ""
    return url.rstrip("/").rsplit("/", 1)[-1]


def render_moderncv_template(
    template_path: Path,
    *,
    job: JobListing,
    master_cv: MasterCV,
    profile: CandidateProfile,
) -> str:
    """Render a tailored CV by preserving the user's moderncv template.

    Only role-specific text is rewritten. The master template's design,
    section ordering, language toggle, photo, font, and curated narrative
    skill blocks stay intact.
    """
    source = template_path.read_text(encoding="utf-8")
    header_comment = "% Tailored by free-job-agent for " + _inline_latex(f"{job.title} at {job.company}") + "\n"
    source = header_comment + source

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
    for command_name, experience in zip(["expone", "exptwo", "expthree", "expfour", "expfive"], master_cv.experience):
        if _has_command(source, command_name):
            source = _replace_newcommand_body(source, command_name, _experience_body(experience, job))

    # Projects: pick most-relevant projects from master_cv if available.
    if master_cv.projects:
        ranked_projects = sorted(
            master_cv.projects,
            key=lambda project: _keyword_score(project.description + " " + " ".join(project.technologies) + " " + project.name, job),
            reverse=True,
        )
        for command_name, project in zip(["projone", "projtwo", "projthree"], ranked_projects):
            if _has_command(source, command_name):
                source = _replace_newcommand_body(source, command_name, _project_body(project, job))

    return source


def _has_command(source: str, command_name: str) -> bool:
    return rf"\newcommand{{\{command_name}}}" in source


def render_latex_source(
    markdown_content: str,
    title: str = "Tailored CV",
    *,
    template_path: Path | None = None,
    job: JobListing | None = None,
    master_cv: MasterCV | None = None,
    profile: CandidateProfile | None = None,
) -> str:
    """Convert the generated CV markdown into editable LaTeX source.

    When a ``main.tex`` template is provided alongside the job and profile
    data, ``render_moderncv_template`` is used so the CV preserves the user's
    curated design and only role-relevant text is updated. Otherwise this
    falls back to a minimal article-class document built from the Markdown so
    the workflow still produces a valid ``cv.tex`` and PDF.
    """
    if template_path and template_path.exists() and job and master_cv and profile:
        return render_moderncv_template(template_path, job=job, master_cv=master_cv, profile=profile)

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
            body.append(rf"\item {_inline_latex(re.sub(r'^[-*]\s+', '', line))}")
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
        last_result = subprocess.run(
            command,
            cwd=workdir,
            env=_latex_subprocess_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
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
