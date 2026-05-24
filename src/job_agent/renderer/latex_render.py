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
    """Pick the top candidate skills that actually appear in the job posting.

    Only terms that are present in the job's tech_stack, requirements,
    responsibilities, or description are returned. A skill the candidate has
    but the job never mentions is irrelevant for the closing sentence and
    would dilute the signal.
    """
    job_text = " ".join(
        job.tech_stack
        + job.requirements
        + job.responsibilities
        + [job.title]
        + [(job.description or "")[:1500]]
    ).casefold()
    terms: list[str] = []
    seen: set[str] = set()
    # Prefer skills with 2+ year experience first, then anything else.
    sorted_skills = sorted(
        master_cv.skills,
        key=lambda s: (s.years_experience or 0, _skill_score(s, job)),
        reverse=True,
    )
    for skill in sorted_skills:
        name = skill.name.strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        pattern = r"\b" + re.escape(key) + r"\b"
        if re.search(pattern, job_text):
            terms.append(name)
            seen.add(key)
        if len(terms) >= limit:
            break
    return terms


def _is_french(text: str) -> bool:
    return bool(text and _FRENCH_HINT_RE.search(text))


_STAGE_TERMS_RE = re.compile(r"\b(stage|stagiaire|internship|intern|graduate|junior)\b", re.IGNORECASE)
_ALTERNANCE_TERMS_RE = re.compile(r"\b(alternance|apprentissage|apprenti|apprenticeship|alternant|alternant\.e)\b", re.IGNORECASE)
_CDI_TERMS_RE = re.compile(r"\b(cdi|permanent|full[- ]time)\b", re.IGNORECASE)


def _detect_contract_family(job: JobListing) -> str:
    """Best-effort detect: 'stage', 'alternance', 'cdi', or 'role'.

    Looks at title, job_type, description, raw_text. Alternance terms win over
    stage when both appear (alternance is the more specific signal).
    """
    haystack = " ".join([
        job.title or "",
        job.job_type or "",
        (job.description or "")[:1000],
        (job.raw_text or "")[:500],
    ])
    if _ALTERNANCE_TERMS_RE.search(haystack):
        return "alternance"
    if _STAGE_TERMS_RE.search(haystack):
        return "stage"
    if _CDI_TERMS_RE.search(haystack):
        return "cdi"
    return "role"


def _focus_phrase(focus: list[str], french: bool) -> str:
    if not focus:
        return ""
    if french:
        return f", avec un focus sur {', '.join(focus)}"
    return f", with a focus on {', '.join(focus)}"


_LOCATION_TOKENS_RE = re.compile(
    r"\b(paris|île[- ]de[- ]france|ile[- ]de[- ]france|idf|lyon|toulouse|marseille|nantes|lille|bordeaux|"
    r"london|berlin|munich|amsterdam|madrid|barcelona|france|europe|remote|"
    r"\d{1,2}(er|ème|e)?\s+arrondissement?|\d{2,5})\b",
    re.IGNORECASE,
)


_PRIMARY_ROLE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # (pattern, canonical label) — first match wins. Order matters so that
    # "Ingénieur ML et Data scientist" cleans to "Data Scientist", not
    # "Ingénieur ML". French titles are mapped to readable English labels.
    (re.compile(r"\bdata\s+scientist\b", re.IGNORECASE), "Data Scientist"),
    (re.compile(r"\bdata\s+science\b", re.IGNORECASE), "Data Science"),
    (re.compile(r"\bdata\s+engineering\b", re.IGNORECASE), "Data Engineering"),
    (re.compile(r"\bdata\s+engineer\b", re.IGNORECASE), "Data Engineer"),
    (re.compile(r"\bdata\s+analyst\b", re.IGNORECASE), "Data Analyst"),
    (re.compile(r"\bdata\s+analytics?\b", re.IGNORECASE), "Data Analytics"),
    (re.compile(r"\bdata\s+architect\b", re.IGNORECASE), "Data Architect"),
    (re.compile(r"\bml\s+engineer\b", re.IGNORECASE), "Machine Learning Engineer"),
    (re.compile(r"\bmlops\b", re.IGNORECASE), "MLOps Engineer"),
    (re.compile(r"\bai\s+engineer\b", re.IGNORECASE), "AI Engineer"),
    (re.compile(r"\bai\s+researcher\b", re.IGNORECASE), "AI Researcher"),
    (re.compile(r"\bia\s+engineer\b", re.IGNORECASE), "AI Engineer"),
    (re.compile(r"\bmachine\s+learning\b", re.IGNORECASE), "Machine Learning"),
    (re.compile(r"\bdeep\s+learning\b", re.IGNORECASE), "Deep Learning"),
    (re.compile(r"\banalytics\s+engineer\b", re.IGNORECASE), "Analytics Engineer"),
    (re.compile(r"\bbusiness\s+intelligence\b", re.IGNORECASE), "Business Intelligence"),
    (re.compile(r"\bdata\s+intelligence\b", re.IGNORECASE), "Data Intelligence"),
    (re.compile(r"\banalyste\s+(?:data|donn[ée]es)\b", re.IGNORECASE), "Data Analyst"),
    # French generic engineer phrases — map onto crisp English equivalents so
    # the CV reads "Seeking a Data Engineering alternance" instead of
    # "Seeking a Ingénieur en science des données alternance".
    (re.compile(r"\bingénieur\s+en\s+science\s+des\s+donn[ée]es\b", re.IGNORECASE), "Data Engineering"),
    (re.compile(r"\bingénieur\s+(?:données|data)\b", re.IGNORECASE), "Data Engineering"),
    (re.compile(r"\bingénieur\s+ml\b", re.IGNORECASE), "Machine Learning Engineer"),
    (re.compile(r"\bingénieur\s+(?:ia|ai)\b", re.IGNORECASE), "AI Engineer"),
    (re.compile(r"\bingénieur\s+logiciel\b", re.IGNORECASE), "Software Engineer"),
    (re.compile(r"\bscience\s+des\s+donn[ée]es\b", re.IGNORECASE), "Data Science"),
    (re.compile(r"\bd[ée]veloppeur\s+(?:fullstack|full[- ]stack)\b", re.IGNORECASE), "Full-Stack Developer"),
    (re.compile(r"\bd[ée]veloppeur\s+backend\b", re.IGNORECASE), "Backend Developer"),
    # Mid-priority English software roles.
    (re.compile(r"\bsoftware\s+engineer\b", re.IGNORECASE), "Software Engineer"),
    (re.compile(r"\bbackend\s+engineer\b", re.IGNORECASE), "Backend Engineer"),
    (re.compile(r"\bfullstack\s+engineer\b", re.IGNORECASE), "Full-Stack Engineer"),
    (re.compile(r"\bfrontend\s+engineer\b", re.IGNORECASE), "Frontend Engineer"),
    (re.compile(r"\bcloud\s+engineer\b", re.IGNORECASE), "Cloud Engineer"),
    (re.compile(r"\bdevops\b", re.IGNORECASE), "DevOps Engineer"),
]


def _clean_role_phrase(role: str, *, max_words: int = 5) -> str:
    """Strip noisy tokens from a job title to get a short role phrase.

    Strategy: try the high-priority data/AI role patterns first, then mid /
    low priority ones. This means "Ingénieur ML et Data scientist" cleans to
    "Data Scientist", not "Ingénieur ML".
    """
    if not role:
        return ""
    for pattern, label in _PRIMARY_ROLE_PATTERNS:
        if pattern.search(role):
            return label
    value = role
    value = re.sub(r"\(H/F\)|\(F/H\)|\(H/F/X\)|\(M/F\)|\(M/W/D\)|H/F|F/H", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\([^)]*\)", "", value)
    value = _STAGE_TERMS_RE.sub("", value)
    value = _ALTERNANCE_TERMS_RE.sub("", value)
    value = re.sub(
        r"\b(de fin d['’]études|de fin d.études|end[- ]of[- ]studies|sujet de stage|sujet|master|apprentissage|consultant·e|consultant\.e)\b",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = _LOCATION_TOKENS_RE.sub("", value)
    value = re.sub(r"\s*[-–—:/|]+\s*$", "", value)
    value = re.sub(r"^\s*[-–—:/|]+\s*", "", value)
    value = re.sub(r"\s{2,}", " ", value)
    value = value.strip(" -:,;–—")
    words = value.split()
    if len(words) > max_words:
        value = " ".join(words[:max_words])
    return value


def _contract_aware_tail(job: JobListing, focus: list[str], french: bool) -> str:
    """Build a natural-sounding closing sentence for the CV summary.

    Wording per contract family:
    - stage    EN: "Seeking a 6-month {role} internship at {company}"
               FR: "Recherche un stage de 6 mois en tant que {role} chez {company}"
    - alternance EN: "Seeking a {role} alternance at {company}"
                  FR: "Recherche une alternance en tant que {role} chez {company}"
    - cdi      EN: "Open to {role} opportunities at {company}"
               FR: "Ouvert à des opportunités de {role} chez {company}"
    - other    EN: "Applying for the {role} role at {company}"
               FR: "Candidature pour le poste de {role} chez {company}"
    """
    # Resolve the real employer name when the listing was published via an
    # aggregator (France Travail etc.). Falls back to the source company.
    try:
        from job_agent.generator.company_extract import resolve_company_for_letter
        company = resolve_company_for_letter(job).strip()
    except Exception:
        company = (job.company or "").strip()
    role = _clean_role_phrase(job.title or "")
    contract = _detect_contract_family(job)
    # If the cleanup left something that doesn't look like a real role (extra
    # punctuation, underscores, escape leftovers, very short, or just words
    # like "de" / "the"), fall back to a candidate-friendly default rather
    # than print garbage on the CV.
    looks_clean = bool(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\-\.\s]+", role or ""))
    starts_well = bool(re.match(r"^[A-ZÀ-Ý]", role or ""))
    if not role or len(role) < 4 or role.count(" ") > 4 or not looks_clean or not starts_well:
        role = "Data Science / AI" if not french else "Data Science / IA"

    company_suffix = ""
    if company and company.lower() not in {"france travail", "pole emploi", "pôle emploi", "[to be parsed]", "the hiring team", ""}:
        company_suffix = f" at {company}" if not french else f" chez {company}"

    if contract == "stage":
        sentence = (
            f" Recherche un stage de 6 mois en tant que {role}{company_suffix}"
            if french
            else f" Seeking a 6-month {role} internship{company_suffix}"
        )
    elif contract == "alternance":
        sentence = (
            f" Recherche une alternance en tant que {role}{company_suffix}"
            if french
            else f" Seeking a {role} alternance{company_suffix}"
        )
    elif contract == "cdi":
        sentence = (
            f" Ouvert à des opportunités de {role}{company_suffix}"
            if french
            else f" Open to {role} opportunities{company_suffix}"
        )
    else:
        sentence = (
            f" Candidature pour le poste de {role}{company_suffix}"
            if french
            else f" Applying for the {role} role{company_suffix}"
        )
    sentence += _focus_phrase(focus, french)
    sentence += "."
    return sentence


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

    The closing sentence is contract-aware: stage / alternance / CDI / role.
    """
    body = original_body.strip()
    if not body:
        body = _escape_latex((profile.summary or master_cv.summary or "").strip())
    body = re.sub(r"\s+", " ", body).strip()
    # Remove the previous deterministic-closer phrasing if present so we don't
    # stack "Seeking a 6-month internship in France. Seeking a 6-month..."
    body = re.sub(
        r"(?i)\b(seeking|recherche|targeting|candidature)\b[^.]*\.(\s|$)+",
        "",
        body,
    ).strip()
    base = body[:-1] if body.endswith(".") else body
    focus = _job_focus_terms(job, master_cv, limit=4)
    tail = _contract_aware_tail(job, focus, french)
    if not tail.strip():
        return base + "."
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
    for command_name, experience in zip(["expone", "exptwo", "expthree", "expfour", "expfive"], master_cv.experience):
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
                for command_name, project in zip(defined_slots, ranked_projects):
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
