"""FULL_AUTO eligibility gate.

Fill & Confirm can be broad because the user reviews before submission.
FULL_AUTO needs a stricter, auditable fail-closed gate before a browser session
is allowed to submit unattended.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from job_agent.auto_apply.session_types import ApplyMode
from job_agent.config import AppConfig
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, PacketStatus

_SUBMITTED = {JobStatus.APPLIED, JobStatus.SUBMITTED, JobStatus.MANUALLY_SUBMITTED, JobStatus.AUTO_SUBMITTED}
_SAFE_PACKET_STATUSES = {PacketStatus.READY, PacketStatus.NEEDS_REVIEW, PacketStatus.DRAFT}
_HARD_RISK_FLAGS = {"WORK_AUTH_REQUIRED", "LANGUAGE_MISMATCH", "SPONSORSHIP_GATED", "FRENCH_REQUIRED"}


@dataclass(frozen=True)
class FullAutoEligibility:
    eligible: bool
    reasons: list[str]
    score: float
    preflight_verdict: str

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def evaluate_fullauto_eligibility(
    job: JobListing,
    packet: ApplicationPacket,
    *,
    config: AppConfig | Any | None = None,
    mode: ApplyMode = ApplyMode.FULL_AUTO,
) -> FullAutoEligibility:
    cfg = config or AppConfig()
    score = float(packet.fit_score if packet.fit_score is not None else job.fit_score or 0)
    reasons: list[str] = []
    if mode != ApplyMode.FULL_AUTO:
        return FullAutoEligibility(True, [], score, _preflight_verdict(packet))
    if not job.apply_url:
        reasons.append("missing_apply_url")
    if job.status in _SUBMITTED:
        reasons.append("already_submitted")
    if packet.status not in _SAFE_PACKET_STATUSES:
        reasons.append(f"packet_status_{packet.status.value.lower()}")
    min_score = float(getattr(cfg, "fullauto_min_score", 75))
    if score < min_score:
        reasons.append("below_fullauto_score_threshold")
    hard_flags = sorted(set(job.risk_flags + packet.risk_flags) & _HARD_RISK_FLAGS)
    if hard_flags:
        reasons.append("hard_risk_flags:" + ",".join(hard_flags))
    unknown_answers = [answer.question for answer in packet.screening_answers if answer.needs_review]
    if unknown_answers:
        reasons.append("unknown_screening_answers")

    verdict = _preflight_verdict(packet)
    if getattr(cfg, "fullauto_require_preflight_apply", True):
        if not verdict:
            reasons.append("preflight_missing")
        elif verdict != "APPLY":
            reasons.append(f"preflight_{verdict.casefold()}")
    if getattr(cfg, "fullauto_block_sponsorship_gated", True) and "SPONSORSHIP_GATED" in hard_flags:
        reasons.append("sponsorship_gated")

    return FullAutoEligibility(not reasons, _dedupe(reasons), score, verdict)


def evaluate_apply_candidate(candidate: Any, *, config: AppConfig | Any | None = None, mode: ApplyMode) -> FullAutoEligibility:
    return evaluate_fullauto_eligibility(candidate.job, candidate.packet, config=config, mode=mode)


def _preflight_verdict(packet: ApplicationPacket) -> str:
    for artifact in packet.artifacts:
        if artifact.kind != "preflight_json":
            continue
        try:
            payload = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
        except Exception:
            continue
        verdict = str(payload.get("verdict") or "").strip().upper()
        if verdict:
            return verdict
    decision = (packet.fit_decision or "").strip().upper()
    return decision if decision in {"APPLY", "APPLY_WITH_EDITS", "NEEDS_MANUAL", "SKIP"} else ""


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


__all__ = ["FullAutoEligibility", "evaluate_apply_candidate", "evaluate_fullauto_eligibility"]
