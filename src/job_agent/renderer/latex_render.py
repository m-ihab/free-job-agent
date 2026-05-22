"""Render tailored CV content to LaTeX and optionally compile it."""
from __future__ import annotations

from calendar import month_name
import re
import shutil
import subprocess
from pathlib import Path

from job_agent.schemas.candidate import CandidateProfile, MasterCV, Project, Skill, WorkExperience
from job_agent.schemas.job import JobListing


class LatexCompileError(RuntimeError):
    """Raised when a LaTeX compiler exists but cannot build the PDF."""


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


def _education_body(education, job: JobListing) -> str:
    date = ""
    if education.start_year or education.end_year:
        date = f"{education.start_year or ''} -- {education.end_year or 'Present'}"
    title = education.degree
    if education.field:
        title = f"{title} in {education.field}"
    details = _latex_itemize(education.notes)
    return _cventry(date, title, education.institution, education.location or "", details)


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


def _skill_names(skills: list[Skill], categories: set[str], job: JobListing) -> str:
    selected = [skill for skill in skills if (skill.category or "").casefold() in categories]
    ranked = sorted(selected, key=lambda skill: (_skill_score(skill, job), skill.name.casefold()), reverse=True)
    return ", ".join(_inline_latex(skill.name) for skill in ranked)


def _language_line(profile: CandidateProfile) -> str:
    parts = []
    for language in profile.languages:
        if " - " in language:
            name, level = language.split(" - ", 1)
        else:
            name, level = language, ""
        if level:
            parts.append(rf"\textbf{{{_inline_latex(name)}}} -- {_inline_latex(level)}")
        else:
            parts.append(_inline_latex(name))
    return r" \quad|\quad ".join(parts)


def _replace_newcommand_body(source: str, command_name: str, body: str) -> str:
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
    """Render a tailored CV by preserving the user's moderncv template."""
    source = template_path.read_text(encoding="utf-8")
    contact = master_cv.contact
    names = contact.name.split()
    first_name = names[0] if names else contact.name
    last_name = " ".join(names[1:]) if len(names) > 1 else ""

    source = _replace_line_command(source, r"^\\name\{.*?\}\{.*?\}$", rf"\name{{{_inline_latex(first_name)}}}{{{_inline_latex(last_name)}}}")
    source = _replace_line_command(source, r"^\\address\{.*?\}\{.*?\}\{.*?\}$", rf"\address{{{_inline_latex(contact.location or '')}}}{{}}{{}}")
    source = _replace_line_command(source, r"^\\phone\[mobile\]\{.*?\}$", rf"\phone[mobile]{{{_inline_latex(contact.phone or '')}}}")
    source = _replace_line_command(source, r"^\\email\{.*?\}$", rf"\email{{{_inline_latex(contact.email)}}}")
    if contact.linkedin_url:
        source = _replace_line_command(source, r"^\\social\[linkedin\]\{.*?\}$", rf"\social[linkedin]{{{_inline_latex(_linkedin_handle(contact.linkedin_url))}}}")
    if contact.github_url:
        github_command = rf"\social[github]{{{_inline_latex(_github_handle(contact.github_url))}}}"
        if re.search(r"^%?\s*\\social\[github\]\{.*?\}$", source, flags=re.MULTILINE):
            source = _replace_line_command(source, r"^%?\s*\\social\[github\]\{.*?\}$", github_command)
        else:
            source = source.replace(r"\social[linkedin]", github_command + "\n" + r"\social[linkedin]", 1)

    relevant_skill_names = [skill.name for skill in sorted(master_cv.skills, key=lambda skill: _skill_score(skill, job), reverse=True) if _skill_score(skill, job) > 0]
    summary = profile.summary or master_cv.summary
    if relevant_skill_names:
        summary = f"{summary} Most relevant for this role: {', '.join(relevant_skill_names[:6])}."
    source = _replace_newcommand_body(source, "mysummary", _inline_latex(summary))

    for command_name, education in zip(["eduone", "edutwo"], master_cv.education):
        source = _replace_newcommand_body(source, command_name, _education_body(education, job))

    for command_name, experience in zip(["expone", "exptwo", "expthree"], master_cv.experience):
        source = _replace_newcommand_body(source, command_name, _experience_body(experience, job))

    for command_name, project in zip(["projone"], sorted(master_cv.projects, key=lambda project: _keyword_score(project.description + " " + " ".join(project.technologies), job), reverse=True)):
        source = _replace_newcommand_body(source, command_name, _project_body(project, job))

    skills = master_cv.skills or profile.skills
    source = _replace_newcommand_body(source, "skillsml", _skill_names(skills, {"machine_learning"}, job))
    source = _replace_newcommand_body(source, "skillsdata", _skill_names(skills, {"data", "data_engineering"}, job))
    source = _replace_newcommand_body(source, "skillsprog", _skill_names(skills, {"programming"}, job))
    source = _replace_newcommand_body(source, "skillscloud", _skill_names(skills, {"cloud", "platforms"}, job))
    source = _replace_newcommand_body(source, "skillstools", _skill_names(skills, {"tools", "analytics", "automation"}, job))
    if profile.languages:
        source = _replace_newcommand_body(source, "skillslang", _language_line(profile))
    return source


def render_latex_source(
    markdown_content: str,
    title: str = "Tailored CV",
    *,
    template_path: Path | None = None,
    job: JobListing | None = None,
    master_cv: MasterCV | None = None,
    profile: CandidateProfile | None = None,
) -> str:
    """Convert the generated CV markdown into editable LaTeX source."""
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


def available_latex_compiler() -> str | None:
    """Return the best available LaTeX compiler executable."""
    for command in ["latexmk", "pdflatex", "xelatex", "lualatex"]:
        found = shutil.which(command)
        if found:
            return found
    return None


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
    return output_pdf
