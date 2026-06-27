"""Work-authorization routing by contract kind."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing


class WorkAuthClass(str, Enum):
    DIRECTLY_APPLICABLE = "directly_applicable"
    SPONSORSHIP_GATED = "sponsorship_gated"
    UNKNOWN = "unknown"


class ContractKind(str, Enum):
    STAGE = "stage"
    ALTERNANCE = "alternance"
    CDD = "cdd"
    CDI = "cdi"
    INTERIM = "interim"
    FREELANCE = "freelance"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class WorkAuthAssessment:
    work_auth_class: WorkAuthClass
    contract_kind: ContractKind
    blocking: bool
    rationale: str
    notes: list[str]


_CONTRACT_SIGNALS: list[tuple[ContractKind, tuple[str, ...]]] = [
    (ContractKind.ALTERNANCE, ("alternance", "apprentissage", "apprenticeship", "apprentice")),
    (ContractKind.STAGE, ("stage", "stagiaire", "internship", "intern ")),
    (ContractKind.CDI, ("cdi", "permanent", "full time", "full-time")),
    (ContractKind.CDD, ("cdd", "fixed term", "fixed-term")),
    (ContractKind.INTERIM, ("interim", "intérim", "temporary")),
    (ContractKind.FREELANCE, ("freelance", "contractor", "independent")),
]


def detect_contract_kind(job: JobListing) -> ContractKind:
    text = " ".join(
        [
            job.job_type or "",
            job.title or "",
            job.description or "",
            " ".join(job.requirements or []),
        ]
    ).casefold()
    padded = f" {text} "
    for kind, signals in _CONTRACT_SIGNALS:
        if any(signal in padded for signal in signals):
            return kind
    return ContractKind.UNKNOWN


def classify_work_auth(job: JobListing, candidate: CandidateProfile) -> WorkAuthAssessment:
    contract = detect_contract_kind(job)
    notes: list[str] = []
    auth_text = " ".join(
        [
            getattr(candidate, "work_auth_status", "") or "",
            " ".join(getattr(candidate, "work_authorizations", []) or []),
            getattr(candidate.contact, "work_authorization", "") or "",
        ]
    ).casefold()

    if _has_direct_eu_auth(auth_text):
        return WorkAuthAssessment(
            WorkAuthClass.DIRECTLY_APPLICABLE,
            contract,
            False,
            "Candidate profile lists direct France/EU work authorization.",
            ["EU/France authorization present in profile"],
        )

    can_stage = bool(getattr(candidate, "can_do_stage", False))
    has_convention = bool(getattr(candidate, "convention_de_stage_available", False))
    needs_cdi_sponsorship = bool(getattr(candidate, "needs_sponsorship_for_cdi", False))
    student_like = "student" in auth_text or "étudiant" in auth_text or "etudiant" in auth_text

    if contract in {ContractKind.STAGE, ContractKind.ALTERNANCE}:
        if can_stage or has_convention:
            detail = "stage/alternance covered by profile stage eligibility"
            if has_convention:
                notes.append("Convention de stage marked available")
            return WorkAuthAssessment(WorkAuthClass.DIRECTLY_APPLICABLE, contract, False, detail, notes)
        if student_like:
            return WorkAuthAssessment(
                WorkAuthClass.UNKNOWN,
                contract,
                False,
                "Student status present, but stage/convention facts are not locked in profile.",
                ["Verify convention de stage / alternance eligibility"],
            )

    if contract == ContractKind.CDI and needs_cdi_sponsorship:
        return WorkAuthAssessment(
            WorkAuthClass.SPONSORSHIP_GATED,
            contract,
            True,
            "CDI appears to require sponsorship or a work-authorization change.",
            ["Needs sponsorship for CDI according to profile"],
        )

    if _job_mentions_no_sponsorship(job):
        return WorkAuthAssessment(
            WorkAuthClass.SPONSORSHIP_GATED,
            contract,
            True,
            "Job text signals no sponsorship or strict existing work authorization.",
            ["Job mentions sponsorship/work-authorization restriction"],
        )

    return WorkAuthAssessment(
        WorkAuthClass.UNKNOWN,
        contract,
        False,
        "No decisive work-authorization route detected; verify before applying.",
        ["Verify work authorization requirements"],
    )


def _has_direct_eu_auth(auth_text: str) -> bool:
    direct = ("eu citizen", "european citizen", "french citizen", "citoyen", "citizen")
    return any(signal in auth_text for signal in direct)


def _job_mentions_no_sponsorship(job: JobListing) -> bool:
    text = f"{job.title} {job.description} {' '.join(job.requirements or [])}".casefold()
    signals = (
        "no sponsorship",
        "visa sponsorship not available",
        "must be authorized to work",
        "autorisation de travail",
        "titre de séjour",
        "titre de sejour",
    )
    return any(signal in text for signal in signals)
