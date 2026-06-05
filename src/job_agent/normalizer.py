"""Normalize raw job text into a structured JobListing."""
from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

from job_agent.timeutil import utc_now

if TYPE_CHECKING:
    from job_agent.schemas.job import JobListing

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}
SALARY_RE = re.compile(
    r"(?P<cur>[$€£])?\s*(?P<a>\d{2,3}(?:[\s,]?\d{3})?|\d{2,3}\s?k)\s*(?:[-–to]+\s*(?P<cur2>[$€£])?\s*(?P<b>\d{2,3}(?:[\s,]?\d{3})?|\d{2,3}\s?k))?\s*(?:/\s*(?:yr|year|annum|an|hr|hour|mo|month))?",
    re.IGNORECASE,
)
REMOTE_KEYWORDS = {"remote", "work from home", "wfh", "distributed", "anywhere", "télétravail", "teletravail", "travail à distance", "travail a distance"}
HYBRID_KEYWORDS = {"hybrid", "hybride", "part remote", "partially remote", "télétravail partiel", "teletravail partiel"}
ONSITE_KEYWORDS = {"on-site", "onsite", "office-based", "office based", "présentiel", "presentiel", "sur site"}
SENIORITY_KEYWORDS = {
    "intern": ["intern", "internship", "stagiaire", "stage", "alternance", "apprentissage", "apprenti"],
    "junior": ["junior", "entry level", "graduate", "débutant", "debutant"],
    "mid": ["mid-level", "mid level", "intermediate"],
    "senior": ["senior", "sr.", "lead", "principal", "staff"],
}
LANGUAGE_KEYWORDS = {
    "English": ["english"],
    "French": ["french", "français", "francais", "francophone"],
    "German": ["german", "deutsch"],
    "Spanish": ["spanish", "español", "espanol"],
}
TECH_KEYWORDS = {
    "python", "java", "javascript", "typescript", "go", "golang", "rust", "c++", "c#",
    "ruby", "scala", "kotlin", "swift", "php", "r", "sql", "nosql", "postgres",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "docker", "kubernetes",
    "k8s", "aws", "gcp", "azure", "terraform", "react", "vue", "angular", "node",
    "nodejs", "django", "fastapi", "flask", "spring", "rails", "graphql", "rest", "grpc",
    "kafka", "spark", "hadoop", "airflow", "dbt", "pandas", "numpy", "pytorch", "tensorflow",
    "scikit-learn", "sklearn", "machine learning", "ml", "ai", "llm", "nlp", "computer vision",
    "linux", "git", "ci/cd", "jenkins", "github actions", "gitlab", "ansible", "tableau",
    "power bi", "looker", "snowflake", "bigquery", "databricks", "excel", "vba", "power query",
    "dataiku", "mlops", "hugging face", "langchain", "rag", "generative ai", "genai",
    "intelligence artificielle", "apprentissage automatique", "statistiques", "modélisation", "modelisation",
}
SECTION_HEADERS = {
    "requirements": [
        "requirements", "qualifications", "what we're looking for", "what you bring",
        "skills required", "required skills", "about you", "you have",
        "profil recherché", "profil recherche", "compétences", "competences", "prérequis", "prerequis",
    ],
    "responsibilities": [
        "responsibilities", "what you'll do", "duties", "role", "key responsibilities",
        "about the role", "your mission", "missions", "vos missions", "mission", "activités", "activites",
    ],
    "benefits": ["benefits", "perks", "what we offer", "compensation", "we offer", "avantages", "rémunération", "remuneration"],
}


def _extract_tech_stack(text: str) -> list[str]:
    text_lower = text.lower()
    found = []
    for tech in TECH_KEYWORDS:
        if re.search(r"(?<![\w+#.-])" + re.escape(tech.lower()) + r"(?![\w+#.-])", text_lower):
            found.append(tech)
    # Normalize common aliases.
    aliases = {"golang": "go", "postgres": "postgresql", "sklearn": "scikit-learn", "k8s": "kubernetes"}
    normalized = [aliases.get(t, t) for t in found]
    return sorted(set(normalized), key=str.lower)


def _parse_salary_num(value: str) -> int:
    value = value.lower().strip().replace(" ", "").replace(",", "")
    if value.endswith("k"):
        return int(float(value[:-1]) * 1000)
    return int(re.sub(r"[^\d]", "", value))


def _extract_salary(text: str) -> tuple[Optional[int], Optional[int]]:
    for match in SALARY_RE.finditer(text):
        a = match.group("a")
        if not a:
            continue
        try:
            low = _parse_salary_num(a)
        except ValueError:
            continue
        b = match.group("b")
        if b:
            try:
                high = _parse_salary_num(b)
            except ValueError:
                high = None
            if high is not None:
                return min(low, high), max(low, high)
        if low >= 1000:
            return low, None
    return None, None


def _extract_salary_currency(text: str, default: str = "USD") -> str:
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code
    lowered = text.lower()
    if "eur" in lowered or "euro" in lowered:
        return "EUR"
    if "gbp" in lowered or "pound" in lowered:
        return "GBP"
    return default


def _is_remote(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in REMOTE_KEYWORDS)


def _work_mode(text: str) -> Optional[str]:
    lower = text.lower()
    if any(kw in lower for kw in REMOTE_KEYWORDS):
        return "remote"
    if any(kw in lower for kw in HYBRID_KEYWORDS):
        return "hybrid"
    if any(kw in lower for kw in ONSITE_KEYWORDS):
        return "onsite"
    return None


def _seniority(text: str) -> Optional[str]:
    lower = text.lower()
    for label, keywords in SENIORITY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return label
    return None


def _languages(text: str) -> list[str]:
    lower = text.lower()
    return [name for name, kws in LANGUAGE_KEYWORDS.items() if any(k in lower for k in kws)]


def _extract_lines_after_header(text: str, headers: list[str]) -> list[str]:
    lines = text.splitlines()
    collecting = False
    results: list[str] = []
    all_headers = [h for headers_list in SECTION_HEADERS.values() for h in headers_list]
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower().rstrip(":")
        if lower in headers or any(lower.startswith(h) for h in headers):
            collecting = True
            continue
        is_header = any(lower.startswith(h) for h in all_headers)
        if is_header and collecting:
            break
        if collecting:
            clean = re.sub(r"^[-•*]\s*", "", stripped)
            if clean:
                results.append(clean)
    return results[:20]


def _extract_location(text: str) -> Optional[str]:
    match = re.search(r"(?:Location|Lieu)\s*[:\-]\s*([^\n]{2,100})", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip(" .")
    return None


def _guess_title(text: str) -> Optional[str]:
    for line in text.splitlines():
        clean = line.strip(" #\t")
        if clean and 4 <= len(clean) <= 120 and not clean.lower().startswith(("about ", "we are ")):
            return clean
    return None


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RECRUITER_LABEL_RE = re.compile(
    r"(?:Contact|Recruiter|Hiring Manager|Recruteur|Responsable RH|Contact RH|RH|HR Contact|Talent Acquisition)\s*[:\-]\s*([A-Z][A-Za-zéèêëàâùûôîïçœ-]+(?: [A-Z][A-Za-zéèêëàâùûôîïçœ-]+){1,3})",
    re.IGNORECASE,
)


def _extract_recruiter(text: str) -> tuple[str | None, str | None]:
    """Extract recruiter name and email from raw job text.

    Only extracts information explicitly present in the text — never infers or
    invents. Returns (name, email), either can be None.
    """
    try:
        name: str | None = None
        email: str | None = None
        match = _RECRUITER_LABEL_RE.search(text)
        if match:
            name = match.group(1).strip()
        email_match = _EMAIL_RE.search(text)
        if email_match:
            candidate = email_match.group(0)
            # Skip generic role addresses — not a recruiter's personal email.
            # Split on common separators to avoid substring false-positives like
            # "johiring@corp.fr" matching "hiring".
            local = candidate.split("@")[0].lower()
            local_parts = set(re.split(r"[._+\-]", local))
            _GENERIC_LOCALS = {
                "noreply", "no-reply", "info", "jobs", "careers", "hiring",
                "recrutement", "recruteur", "contact", "apply", "hr", "rh",
                "applications", "candidature",
            }
            if not (local in _GENERIC_LOCALS or local_parts & _GENERIC_LOCALS):
                email = candidate
        return name, email
    except Exception:
        return None, None


def _guess_company(text: str, fallback: str) -> str:
    patterns = [
        r"(?:at|@)\s+([A-Z][A-Za-z0-9&.,'\- ]{2,60})",
        r"Company\s*[:\-]\s*([^\n]{2,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            company = match.group(1).strip(" .,-")
            if company:
                return company
    return fallback


def normalize(job: "JobListing") -> "JobListing":
    """Fill in structured fields from raw_text using deterministic rules."""
    text = job.raw_text or job.description or ""
    combined_location_text = text + " " + (job.location or "")

    if not job.tech_stack:
        job.tech_stack = _extract_tech_stack(text)
    if not job.remote:
        job.remote = _is_remote(combined_location_text)
    if not job.location:
        job.location = _extract_location(text)
    combined_location_text = text + " " + (job.location or "")
    if not job.work_mode:
        job.work_mode = _work_mode(combined_location_text)
    if not job.seniority:
        job.seniority = _seniority((job.title or "") + "\n" + text)
    if not job.languages:
        job.languages = _languages(text)
    if job.salary_min is None and job.salary_max is None:
        job.salary_min, job.salary_max = _extract_salary(text)
    if job.salary_currency == "USD":
        job.salary_currency = _extract_salary_currency(text, default=job.salary_currency)
    if not job.requirements:
        job.requirements = _extract_lines_after_header(text, SECTION_HEADERS["requirements"])
    if not job.responsibilities:
        job.responsibilities = _extract_lines_after_header(text, SECTION_HEADERS["responsibilities"])
    if not job.benefits:
        job.benefits = _extract_lines_after_header(text, SECTION_HEADERS["benefits"])
    if job.title == "[To Be Parsed]":
        guessed = _guess_title(text)
        if guessed:
            job.title = guessed
    if job.company == "[To Be Parsed]":
        job.company = _guess_company(text, job.company)
    if job.recruiter_name is None and job.recruiter_email is None:
        job.recruiter_name, job.recruiter_email = _extract_recruiter(text)
    if not job.apply_url and job.source_url:
        job.apply_url = job.source_url
    if not job.description and text:
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
        if paragraphs:
            job.description = paragraphs[0][:3000]
    job.updated_at = utc_now()
    return job
