"""Job-aware CV tailoring for LaTeX output (split from latex_helpers.py, R1 2026-07-09).

Ranks and renders schema content against a specific job posting: keyword
scoring, contract-family detection (stage/alternance/CDI), role-phrase
cleanup, and the tailored summary's closing sentence.
"""
from __future__ import annotations

import re

from job_agent.renderer.latex_text import (
    _cventry,
    _date_range,
    _escape_latex,
    _inline_latex,
    _latex_itemize,
)
from job_agent.schemas.candidate import CandidateProfile, MasterCV, Project, Skill, WorkExperience
from job_agent.schemas.job import JobListing

_FRENCH_HINT_RE = re.compile(r"[éèêëàâäîïôöùûüç]|stage|alternance|stagiaire", re.IGNORECASE)


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


_STAGE_TERMS_RE = re.compile(r"\b(stage|stagiaire|internship|intern)\b", re.IGNORECASE)
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
            f" Disponible immédiatement pour un stage de 6 mois en tant que {role}{company_suffix}"
            if french
            else f" Available immediately for a 6-month {role} internship{company_suffix}"
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
