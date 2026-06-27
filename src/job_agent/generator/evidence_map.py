"""Map job keywords to grounded candidate evidence."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from job_agent.evidence import EvidenceItem, EvidenceStore
from job_agent.schemas.job import JobListing

_BROAD_KEYWORDS = {"ai", "data", "digital", "team", "tools", "software", "tech"}

_KEYWORD_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Python", ("python",)),
    ("SQL", ("sql", "postgresql", "mysql", "sqlite", "t-sql")),
    ("Machine Learning", ("machine learning", "ml", "model training", "modelisation", "modeling")),
    ("Deep Learning", ("deep learning", "neural network", "pytorch", "tensorflow", "keras")),
    ("NLP", ("nlp", "natural language", "text mining", "llm")),
    ("LLM", ("llm", "large language model", "genai", "generative ai", "rag")),
    ("RAG", ("rag", "retrieval augmented generation", "vector database")),
    ("MLOps", ("mlops", "mlflow", "model deployment", "model registry")),
    ("Docker", ("docker", "container", "containerisation", "containerization")),
    ("Kubernetes", ("kubernetes", "k8s")),
    ("FastAPI", ("fastapi", "fast api")),
    ("Flask", ("flask",)),
    ("Django", ("django",)),
    ("Pandas", ("pandas",)),
    ("NumPy", ("numpy",)),
    ("scikit-learn", ("scikit-learn", "sklearn", "scikit learn")),
    ("Spark", ("spark", "pyspark", "apache spark")),
    ("Airflow", ("airflow",)),
    ("dbt", ("dbt",)),
    ("Power BI", ("power bi", "powerbi")),
    ("Tableau", ("tableau",)),
    ("Excel", ("excel", "vba")),
    ("AWS", ("aws", "amazon web services", "s3", "lambda", "ec2")),
    ("Azure", ("azure",)),
    ("GCP", ("gcp", "google cloud", "bigquery")),
    ("Git", ("git", "github", "gitlab")),
    ("Statistics", ("statistics", "statistiques", "statistical", "regression")),
    ("Data Engineering", ("data engineering", "etl", "elt", "pipeline", "data pipeline")),
    ("Business Intelligence", ("business intelligence", "bi reporting", "dashboard")),
)

_MUST_HAVE_SIGNALS = (
    "required",
    "must have",
    "must-have",
    "mandatory",
    "essential",
    "exige",
    "exigee",
    "obligatoire",
    "requis",
    "requise",
    "indispensable",
)


@dataclass(frozen=True)
class EvidenceKeyword:
    keyword: str
    required: bool
    supported: bool
    evidence_items: list[EvidenceItem]
    confidence: float


@dataclass(frozen=True)
class EvidenceMap:
    rows: list[EvidenceKeyword]
    keyword_coverage: float
    must_have_coverage: float
    safe_keywords_to_add: list[str]
    unsafe_claims_to_avoid: list[str]
    best_evidence_items: list[EvidenceItem]

    def to_dict(self) -> dict[str, object]:
        return {
            "rows": [
                {
                    "keyword": row.keyword,
                    "required": row.required,
                    "supported": row.supported,
                    "confidence": row.confidence,
                    "evidence_items": [item.__dict__ for item in row.evidence_items],
                }
                for row in self.rows
            ],
            "keyword_coverage": self.keyword_coverage,
            "must_have_coverage": self.must_have_coverage,
            "safe_keywords_to_add": self.safe_keywords_to_add,
            "unsafe_claims_to_avoid": self.unsafe_claims_to_avoid,
            "best_evidence_items": [item.__dict__ for item in self.best_evidence_items],
        }


def build_evidence_map(job: JobListing, evidence: EvidenceStore) -> EvidenceMap:
    """Return evidence support for every meaningful keyword in the job."""
    keywords = extract_job_keywords(job)
    required = set(extract_must_have_keywords(job))
    rows: list[EvidenceKeyword] = []

    for keyword in keywords:
        items = evidence.for_keyword(keyword)
        confidence = round(max((item.confidence for item in items), default=0.0), 2)
        rows.append(
            EvidenceKeyword(
                keyword=keyword,
                required=keyword in required,
                supported=bool(items),
                evidence_items=items[:5],
                confidence=confidence,
            )
        )

    supported = [row for row in rows if row.supported]
    required_rows = [row for row in rows if row.required]
    safe = [row.keyword for row in supported]
    unsafe = [row.keyword for row in rows if not row.supported]
    best = _dedupe_items(item for row in supported for item in row.evidence_items)

    return EvidenceMap(
        rows=rows,
        keyword_coverage=_coverage(len(supported), len(rows)),
        must_have_coverage=_coverage(len([row for row in required_rows if row.supported]), len(required_rows)),
        safe_keywords_to_add=safe,
        unsafe_claims_to_avoid=unsafe,
        best_evidence_items=best[:8],
    )


def extract_job_keywords(job: JobListing) -> list[str]:
    """Extract stable ATS-style keywords from a job without keyword salad."""
    seen: set[str] = set()
    result: list[str] = []

    def add(keyword: str) -> None:
        clean = _clean_keyword(keyword)
        if not clean or clean.casefold() in _BROAD_KEYWORDS:
            return
        key = _normalise(clean)
        if key and key not in seen:
            seen.add(key)
            result.append(clean)

    for tech in job.tech_stack:
        add(_canonical_keyword(tech))

    text = _job_text(job)
    norm_text = _normalise(text)
    for canonical, aliases in _KEYWORD_PATTERNS:
        if any(_phrase_in_text(alias, norm_text) for alias in aliases):
            add(canonical)

    return result


def extract_must_have_keywords(job: JobListing) -> list[str]:
    """Extract required keywords from explicit must-have lines."""
    lines = list(job.requirements or [])
    for raw_line in (job.description or "").splitlines():
        if any(signal in _normalise(raw_line) for signal in _MUST_HAVE_SIGNALS):
            lines.append(raw_line)
    if not lines:
        return []

    probe = JobListing(
        title=job.title,
        company=job.company,
        description="\n".join(lines),
        requirements=lines,
        tech_stack=[],
    )
    return extract_job_keywords(probe)


def _job_text(job: JobListing) -> str:
    return " ".join(
        [
            job.title or "",
            job.description or "",
            " ".join(job.requirements or []),
            " ".join(job.responsibilities or []),
            " ".join(job.tech_stack or []),
        ]
    )


def _canonical_keyword(keyword: str) -> str:
    norm = _normalise(keyword)
    for canonical, aliases in _KEYWORD_PATTERNS:
        if any(_phrase_in_text(alias, norm) for alias in aliases):
            return canonical
    return keyword


def _clean_keyword(keyword: str) -> str:
    clean = re.sub(r"\s+", " ", keyword.strip(" -;,."))
    if len(clean) < 2 or len(clean) > 42:
        return ""
    return clean


def _normalise(value: str) -> str:
    without_accents = "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9+#./-]+", " ", without_accents).strip()


def _phrase_in_text(phrase: str, text: str) -> bool:
    norm = _normalise(phrase)
    if not norm:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(norm)}(?![a-z0-9])", text) is not None


def _coverage(matched: int, total: int) -> float:
    if total <= 0:
        return 1.0
    return round(matched / total, 2)


def _dedupe_items(items: Iterable[EvidenceItem]) -> list[EvidenceItem]:
    result: list[EvidenceItem] = []
    seen: set[tuple[str, str, str | None]] = set()
    for item in items:
        key = (item.kind, item.label.casefold(), item.source_ref)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
