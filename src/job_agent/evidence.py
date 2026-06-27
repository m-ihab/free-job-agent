"""Grounded candidate evidence extracted from local profile files."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.schemas.candidate import CandidateProfile, MasterCV, QAProfile
from job_agent.utils import fuzzy
from job_agent.validators import load_profile_bundle

_MATCH_MIN = 70


@dataclass(frozen=True)
class EvidenceItem:
    kind: str
    label: str
    value: str
    source: str
    source_ref: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class EvidenceMatch:
    matched: bool
    items: list[EvidenceItem]
    confidence: float


class EvidenceStore:
    def __init__(self, db: Database, items: Iterable[EvidenceItem] | None = None) -> None:
        self._db = db
        self._items = list(items or [])

    @classmethod
    def load(cls, config: AppConfig) -> "EvidenceStore":
        db = Database(config.db_path)  # type: ignore[arg-type]
        db.initialize()
        return cls(db, [_item_from_row(row) for row in db.list_evidence_items()])

    def all(self) -> list[EvidenceItem]:
        return list(self._items)

    def rebuild(self, config: AppConfig) -> None:
        profile, master_cv, qa_profile = load_profile_bundle(config)
        self._items = build_evidence_items(profile, master_cv, qa_profile)
        self._db.replace_evidence_items([asdict(item) for item in self._items])

    def index(self) -> dict[str, list[EvidenceItem]]:
        result: dict[str, list[EvidenceItem]] = {}
        for item in self._items:
            for token in _tokens(f"{item.label} {item.value}"):
                result.setdefault(token, []).append(item)
        return result

    def for_keyword(self, keyword: str) -> list[EvidenceItem]:
        needle = _normalise(keyword)
        if not needle:
            return []
        matches: list[EvidenceItem] = []
        for item in self._items:
            haystack = _normalise(f"{item.label} {item.value}")
            if needle in haystack or fuzzy.partial_ratio(needle, haystack) >= _MATCH_MIN:
                matches.append(item)
        return matches

    def supports(self, claim: str) -> EvidenceMatch:
        claim_numbers = _numbers(claim)
        evidence_text = _normalise(" ".join(f"{item.label} {item.value}" for item in self._items))
        if any(number not in evidence_text for number in claim_numbers):
            return EvidenceMatch(False, [], 0)

        claim_tokens = set(_tokens(claim))
        if not claim_tokens:
            return EvidenceMatch(False, [], 0)
        scored: list[tuple[float, EvidenceItem]] = []
        required = 1 if len(claim_tokens) <= 2 else 2
        for item in self._items:
            item_tokens = set(_tokens(f"{item.label} {item.value}"))
            overlap = claim_tokens & item_tokens
            if len(overlap) >= required:
                score = len(overlap) / len(claim_tokens) * item.confidence
                scored.append((score, item))
        if not scored:
            return EvidenceMatch(False, [], 0)
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[:5]
        confidence = round(max(score for score, _item in top), 2)
        return EvidenceMatch(confidence >= 0.25, [item for _score, item in top], confidence)


def build_evidence_items(
    profile: CandidateProfile,
    master_cv: MasterCV,
    qa_profile: QAProfile,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    _add_profile_items(items, profile)
    _add_master_cv_items(items, master_cv)
    _add_qa_items(items, qa_profile)
    return _dedupe(items)


def _add_profile_items(items: list[EvidenceItem], profile: CandidateProfile) -> None:
    for skill in profile.skills:
        detail = f"{skill.category}; {skill.years_experience:g} years" if skill.years_experience else skill.category
        items.append(EvidenceItem("skill", skill.name, detail, "profile", "candidate_profile.skills"))
    for language in profile.languages:
        items.append(EvidenceItem("language", language, language, "profile", "candidate_profile.languages"))
    for auth in profile.work_authorizations:
        items.append(EvidenceItem("work_authorization", auth, auth, "profile", "candidate_profile.work_authorizations"))


def _add_master_cv_items(items: list[EvidenceItem], master_cv: MasterCV) -> None:
    for skill in master_cv.skills:
        detail = f"{skill.category}; {skill.years_experience:g} years" if skill.years_experience else skill.category
        items.append(EvidenceItem("skill", skill.name, detail, "cv", "master_cv.skills"))
    for index, exp in enumerate(master_cv.experience):
        value = " ".join(exp.bullet_points + exp.technologies)
        items.append(EvidenceItem("experience", f"{exp.title} at {exp.company}", value, "cv", f"master_cv.experience[{index}]"))
    for index, project in enumerate(master_cv.projects):
        value = " ".join([project.description, *project.bullet_points, *project.technologies])
        items.append(EvidenceItem("project", project.name, value, "cv", project.url or f"master_cv.projects[{index}]"))
    for index, edu in enumerate(master_cv.education):
        value = " ".join([edu.degree, edu.field, edu.location or "", *edu.honors, *edu.notes])
        items.append(EvidenceItem("education", edu.institution, value, "cv", f"master_cv.education[{index}]"))
    for index, cert in enumerate(master_cv.certifications):
        value = " ".join(filter(None, [cert.issuer, str(cert.year or ""), cert.url or ""]))
        items.append(EvidenceItem("certification", cert.name, value, "cv", f"master_cv.certifications[{index}]"))


def _add_qa_items(items: list[EvidenceItem], qa_profile: QAProfile) -> None:
    for entry in qa_profile.entries:
        if not entry.locked:
            continue
        value = str(entry.answer)
        items.append(
            EvidenceItem(
                "screening_answer",
                entry.category,
                value,
                "master_qa_profile",
                entry.id,
                1.0 if not entry.sensitive else 0.95,
            )
        )


def _dedupe(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[tuple[str, str, str, str | None]] = set()
    result: list[EvidenceItem] = []
    for item in items:
        key = (item.kind, _normalise(item.label), _normalise(item.value), item.source_ref)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _item_from_row(row: dict) -> EvidenceItem:
    return EvidenceItem(
        kind=str(row["kind"]),
        label=str(row["label"]),
        value=str(row.get("value") or ""),
        source=str(row["source"]),
        source_ref=row.get("source_ref"),
        confidence=float(row.get("confidence", 1.0)),
    )


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _tokens(value: str) -> list[str]:
    return [token for token in _normalise(value).split() if len(token) >= 3]


def _numbers(value: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?%?", value.casefold())
