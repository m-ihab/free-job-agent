"""Normalize raw job text into a structured JobListing."""
from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from job_agent.schemas.job import JobListing

# --- Regex helpers ---

SALARY_RE = re.compile(
    r'\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?(?:\s*/\s*(?:yr|year|hr|hour|mo|month))?',
    re.IGNORECASE,
)

REMOTE_KEYWORDS = {"remote", "work from home", "wfh", "distributed", "anywhere"}
TECH_KEYWORDS = {
    "python", "java", "javascript", "typescript", "go", "golang", "rust",
    "c++", "c#", "ruby", "scala", "kotlin", "swift", "php", "sql", "nosql",
    "postgres", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "docker", "kubernetes", "k8s", "aws", "gcp", "azure", "terraform",
    "react", "vue", "angular", "node", "nodejs", "django", "fastapi",
    "flask", "spring", "rails", "graphql", "rest", "grpc", "kafka",
    "spark", "hadoop", "airflow", "dbt", "pandas", "numpy", "pytorch",
    "tensorflow", "scikit-learn", "sklearn", "linux", "git", "ci/cd",
    "jenkins", "github actions", "gitlab", "ansible",
}

SECTION_HEADERS = {
    "requirements": [
        "requirements", "qualifications", "what we're looking for",
        "what you bring", "skills required",
    ],
    "responsibilities": [
        "responsibilities", "what you'll do", "duties", "role",
        "key responsibilities", "about the role",
    ],
    "benefits": ["benefits", "perks", "what we offer", "compensation", "we offer"],
}


def _extract_tech_stack(text: str) -> list[str]:
    text_lower = text.lower()
    found = []
    for tech in TECH_KEYWORDS:
        pattern = r'\b' + re.escape(tech) + r'\b'
        if re.search(pattern, text_lower):
            found.append(tech)
    return sorted(set(found))


def _extract_salary(text: str) -> tuple[Optional[int], Optional[int]]:
    matches = SALARY_RE.findall(text)
    if not matches:
        return None, None

    def _parse_num(s: str) -> int:
        return int(re.sub(r'[^\d]', '', s.split('/')[0].replace('$', '')))

    nums = []
    for m in matches[:2]:
        parts = re.split(r'[-–]', m)
        for p in parts:
            try:
                nums.append(_parse_num(p))
            except ValueError:
                pass
    if len(nums) >= 2:
        return min(nums[:2]), max(nums[:2])
    if len(nums) == 1:
        return nums[0], None
    return None, None


def _is_remote(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in REMOTE_KEYWORDS)


def _extract_lines_after_header(text: str, headers: list[str]) -> list[str]:
    """Find a section by header and extract bullet lines."""
    lines = text.splitlines()
    collecting = False
    results = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower().rstrip(':')
        if lower in headers or any(lower.startswith(h) for h in headers):
            collecting = True
            continue
        is_header = any(
            stripped.lower().rstrip(':').startswith(h)
            for headers_list in SECTION_HEADERS.values()
            for h in headers_list
        )
        if is_header and collecting:
            break
        if collecting:
            clean = re.sub(r'^[-•*]\s*', '', stripped)
            if clean:
                results.append(clean)
    return results


def normalize(job: "JobListing") -> "JobListing":
    """Fill in structured fields from raw_text using deterministic rules."""
    import datetime
    text = job.raw_text or ""

    if not job.tech_stack:
        job.tech_stack = _extract_tech_stack(text)

    if not job.remote:
        job.remote = _is_remote(text + " " + (job.location or ""))

    if job.salary_min is None and job.salary_max is None:
        job.salary_min, job.salary_max = _extract_salary(text)

    if not job.requirements:
        job.requirements = _extract_lines_after_header(
            text, SECTION_HEADERS["requirements"]
        )

    if not job.responsibilities:
        job.responsibilities = _extract_lines_after_header(
            text, SECTION_HEADERS["responsibilities"]
        )

    if not job.benefits:
        job.benefits = _extract_lines_after_header(
            text, SECTION_HEADERS["benefits"]
        )

    if job.title == "[To Be Parsed]":
        first_line = text.strip().splitlines()[0].strip() if text.strip() else ""
        if first_line and len(first_line) < 120:
            job.title = first_line

    if not job.description and text:
        paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
        if paragraphs:
            job.description = paragraphs[0][:2000]

    job.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return job
