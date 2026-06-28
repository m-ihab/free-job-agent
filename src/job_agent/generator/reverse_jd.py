"""Reverse-JD analysis: explain how a job maps to the local candidate profile."""
from __future__ import annotations

from dataclasses import dataclass

from job_agent.evidence import EvidenceStore
from job_agent.generator.evidence_map import build_evidence_map
from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing


@dataclass(frozen=True)
class ReverseJD:
    role_family: str
    matched_keywords: list[str]
    missing_keywords: list[str]
    safe_keywords_to_surface: list[str]
    evidence_refs: list[str]
    recommendation: str
    caution: str

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def analyze_reverse_jd(job: JobListing, candidate: CandidateProfile, evidence: EvidenceStore) -> ReverseJD:
    evidence_map = build_evidence_map(job, evidence)
    matched = [row.keyword for row in evidence_map.rows if row.supported]
    missing = [row.keyword for row in evidence_map.rows if not row.supported]
    visible = {_norm(skill) for skill in candidate.all_skill_names()}
    safe_to_surface = [kw for kw in matched if _norm(kw) not in visible][:8]
    refs = _evidence_refs(evidence_map.best_evidence_items)
    return ReverseJD(
        role_family=_role_family(job, matched),
        matched_keywords=matched,
        missing_keywords=missing,
        safe_keywords_to_surface=safe_to_surface,
        evidence_refs=refs,
        recommendation=_recommendation(evidence_map.must_have_coverage, evidence_map.keyword_coverage),
        caution=_caution(missing),
    )


def render_reverse_jd_markdown(job: JobListing, candidate: CandidateProfile, evidence: EvidenceStore) -> str:
    result = analyze_reverse_jd(job, candidate, evidence)
    return "\n".join(
        [
            f"# Reverse JD - {job.title} at {job.company}",
            "",
            f"- Role family: {result.role_family}",
            f"- Recommendation: {result.recommendation}",
            f"- Matched keywords: {', '.join(result.matched_keywords) or 'None detected'}",
            f"- Safe keywords to surface: {', '.join(result.safe_keywords_to_surface) or 'None'}",
            f"- Missing keywords: {', '.join(result.missing_keywords) or 'None'}",
            f"- Evidence refs: {', '.join(result.evidence_refs) or 'No local evidence refs found'}",
            f"- Caution: {result.caution}",
            "",
        ]
    )


def _role_family(job: JobListing, matched: list[str]) -> str:
    text = f"{job.title} {' '.join(matched)}".casefold()
    if "data engineering" in text or "etl" in text or "pipeline" in text:
        return "Data Engineering"
    if "machine learning" in text or "deep learning" in text or "mlops" in text:
        return "Machine Learning / AI"
    if "power bi" in text or "tableau" in text or "business intelligence" in text:
        return "Analytics / BI"
    return "Data Science"


def _recommendation(must_have: float, keyword: float) -> str:
    if must_have >= 0.75 and keyword >= 0.60:
        return "Strong enough to tailor and apply."
    if must_have >= 0.45:
        return "Apply with edits; surface backed keywords and avoid unsupported gaps."
    return "Low evidence coverage; keep for learning or manual review."


def _caution(missing: list[str]) -> str:
    if not missing:
        return "No unsupported keywords detected."
    return "Do not claim unsupported keywords unless you add real local evidence first."


def _evidence_refs(items: list) -> list[str]:
    refs: list[str] = []
    for item in items[:8]:
        label = getattr(item, "label", "")
        source_ref = getattr(item, "source_ref", "") or getattr(item, "source", "")
        refs.append(f"{label} ({source_ref})".strip())
    return refs


def _norm(value: str) -> str:
    return " ".join(value.casefold().replace("-", " ").split())


__all__ = ["ReverseJD", "analyze_reverse_jd", "render_reverse_jd_markdown"]
