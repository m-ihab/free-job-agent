"""ATS keyword gap analysis backed by candidate evidence."""
from __future__ import annotations

from dataclasses import dataclass

from job_agent.evidence import EvidenceStore
from job_agent.generator.evidence_map import EvidenceMap, build_evidence_map
from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing


@dataclass(frozen=True)
class AtsGap:
    keyword_coverage: float
    must_have_coverage: float
    missing_must_haves: list[str]
    safe_keywords_to_add: list[str]
    unsafe_claims_to_avoid: list[str]
    unsupported_keywords: list[str]
    already_visible_keywords: list[str]
    evidence_map: EvidenceMap

    def to_dict(self) -> dict[str, object]:
        return {
            "keyword_coverage": self.keyword_coverage,
            "must_have_coverage": self.must_have_coverage,
            "missing_must_haves": self.missing_must_haves,
            "safe_keywords_to_add": self.safe_keywords_to_add,
            "unsafe_claims_to_avoid": self.unsafe_claims_to_avoid,
            "unsupported_keywords": self.unsupported_keywords,
            "already_visible_keywords": self.already_visible_keywords,
            "evidence_map": self.evidence_map.to_dict(),
        }


def compute_ats_gap(job: JobListing, candidate: CandidateProfile, evidence: EvidenceStore) -> AtsGap:
    """Compare a job's ATS keywords with defensible candidate evidence."""
    evidence_map = build_evidence_map(job, evidence)
    candidate_terms = {_norm(skill) for skill in candidate.all_skill_names()}
    already_visible = [
        row.keyword
        for row in evidence_map.rows
        if row.supported and any(_norm(row.keyword) == term or _norm(row.keyword) in term for term in candidate_terms)
    ]
    missing_must = [row.keyword for row in evidence_map.rows if row.required and not row.supported]
    unsafe = list(evidence_map.unsafe_claims_to_avoid)

    return AtsGap(
        keyword_coverage=evidence_map.keyword_coverage,
        must_have_coverage=evidence_map.must_have_coverage,
        missing_must_haves=missing_must,
        safe_keywords_to_add=list(evidence_map.safe_keywords_to_add),
        unsafe_claims_to_avoid=unsafe,
        unsupported_keywords=unsafe,
        already_visible_keywords=already_visible,
        evidence_map=evidence_map,
    )


def _norm(value: str) -> str:
    return " ".join(value.casefold().replace("-", " ").split())
