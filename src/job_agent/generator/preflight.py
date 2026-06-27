"""Application preflight verdicts before spending time on a job."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from job_agent.config import AppConfig
from job_agent.evidence import EvidenceItem, EvidenceStore
from job_agent.generator.ats_gap import AtsGap, compute_ats_gap
from job_agent.generator.qa import extract_screening_questions
from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing
from job_agent.schemas.packet import ApplicationPacket
from job_agent.scorer import score_job
from job_agent.work_auth import WorkAuthClass, classify_work_auth

_APPLY = "APPLY"
_APPLY_WITH_EDITS = "APPLY_WITH_EDITS"
_NEEDS_MANUAL = "NEEDS_MANUAL"
_SKIP = "SKIP"


@dataclass(frozen=True)
class PreflightResult:
    verdict: str
    fit_score: int
    must_have_coverage: float
    keyword_coverage: float
    missing_must_haves: list[str]
    seniority_risk: str
    language_risk: str
    work_auth_risk: str
    salary_risk: str
    unknown_screening_answers: list[str]
    safe_keywords_to_add: list[str]
    unsafe_claims_to_avoid: list[str]
    best_evidence_items: list[EvidenceItem]
    application_effort: str
    recruiter_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "fit_score": self.fit_score,
            "must_have_coverage": self.must_have_coverage,
            "keyword_coverage": self.keyword_coverage,
            "missing_must_haves": self.missing_must_haves,
            "seniority_risk": self.seniority_risk,
            "language_risk": self.language_risk,
            "work_auth_risk": self.work_auth_risk,
            "salary_risk": self.salary_risk,
            "unknown_screening_answers": self.unknown_screening_answers,
            "safe_keywords_to_add": self.safe_keywords_to_add,
            "unsafe_claims_to_avoid": self.unsafe_claims_to_avoid,
            "best_evidence_items": [item.__dict__ for item in self.best_evidence_items],
            "application_effort": self.application_effort,
            "recruiter_confidence": self.recruiter_confidence,
        }


def run_preflight(
    job: JobListing,
    candidate: CandidateProfile,
    evidence: EvidenceStore,
    config: AppConfig,
    packet: ApplicationPacket | None = None,
) -> PreflightResult:
    """Return an honest apply/edit/manual/skip verdict for a job."""
    score = score_job(job, candidate)
    ats_gap = compute_ats_gap(job, candidate, evidence)
    work_auth = classify_work_auth(job, candidate)
    unknown_screening = _unknown_screening_answers(job, packet)

    seniority_risk = _risk_from_flags(score.risk_flags, "SENIORITY_MISMATCH")
    language_risk = _risk_from_flags(score.risk_flags, "FRENCH_REQUIRED")
    salary_risk = _risk_from_flags(score.risk_flags, "SALARY_BELOW_PREFERENCE", medium=True)
    work_auth_risk = _work_auth_risk(work_auth.work_auth_class)

    verdict = _verdict(
        score.total_score,
        ats_gap,
        seniority_risk,
        language_risk,
        salary_risk,
        work_auth_risk,
        unknown_screening,
        getattr(config, "cover_letter_auto_threshold", None) or candidate.min_fit_score or 70,
    )

    return PreflightResult(
        verdict=verdict,
        fit_score=score.total_score,
        must_have_coverage=ats_gap.must_have_coverage,
        keyword_coverage=ats_gap.keyword_coverage,
        missing_must_haves=ats_gap.missing_must_haves,
        seniority_risk=seniority_risk,
        language_risk=language_risk,
        work_auth_risk=work_auth_risk,
        salary_risk=salary_risk,
        unknown_screening_answers=unknown_screening,
        safe_keywords_to_add=ats_gap.safe_keywords_to_add,
        unsafe_claims_to_avoid=ats_gap.unsafe_claims_to_avoid,
        best_evidence_items=ats_gap.evidence_map.best_evidence_items,
        application_effort=_application_effort(unknown_screening, ats_gap, work_auth_risk),
        recruiter_confidence=_recruiter_confidence(score.total_score, score.confidence, ats_gap, verdict),
    )


def _unknown_screening_answers(job: JobListing, packet: ApplicationPacket | None) -> list[str]:
    if packet is not None and packet.screening_answers:
        return [answer.question for answer in packet.screening_answers if getattr(answer, "needs_review", False)]
    return extract_screening_questions(job.raw_text or job.description or "")


def _risk_from_flags(flags: list[str], flag: str, *, medium: bool = False) -> str:
    if flag not in flags:
        return "none"
    return "med" if medium else "high"


def _work_auth_risk(work_auth_class: WorkAuthClass) -> str:
    if work_auth_class == WorkAuthClass.DIRECTLY_APPLICABLE:
        return "none"
    if work_auth_class == WorkAuthClass.SPONSORSHIP_GATED:
        return "high"
    return "med"


def _verdict(
    fit_score: int,
    ats_gap: AtsGap,
    seniority_risk: str,
    language_risk: str,
    salary_risk: str,
    work_auth_risk: str,
    unknown_screening: list[str],
    apply_threshold: int,
) -> str:
    high_risks = {seniority_risk, language_risk, work_auth_risk}
    if "high" in high_risks or fit_score < 45 or ats_gap.must_have_coverage < 0.35:
        return _SKIP
    if unknown_screening:
        return _NEEDS_MANUAL
    if (
        fit_score >= apply_threshold
        and ats_gap.must_have_coverage >= 0.75
        and ats_gap.keyword_coverage >= 0.60
        and salary_risk != "high"
    ):
        return _APPLY
    return _APPLY_WITH_EDITS


def _application_effort(unknown_screening: list[str], ats_gap: AtsGap, work_auth_risk: str) -> str:
    if unknown_screening or work_auth_risk != "none" or len(ats_gap.missing_must_haves) >= 3:
        return "high"
    if ats_gap.must_have_coverage < 0.75 or ats_gap.keyword_coverage < 0.60:
        return "med"
    return "low"


def _recruiter_confidence(fit_score: int, score_confidence: float, ats_gap: AtsGap, verdict: str) -> float:
    value = (
        (fit_score / 100) * 0.45
        + ats_gap.must_have_coverage * 0.25
        + ats_gap.keyword_coverage * 0.20
        + score_confidence * 0.10
    )
    if verdict == _SKIP:
        value -= 0.15
    if verdict == _NEEDS_MANUAL:
        value -= 0.08
    return round(max(0.0, min(1.0, value)), 2)
