"""Side-effecting helpers for an auto-apply session: form fill, candidate
loading, and the DB status writes for submitted / needs-manual hand-offs.

Free functions taking the :class:`AutoApplySession` as ``session``. They call
package-level driver helpers and the session's own ``_emit`` / ``_mark_*``
methods so the auto-apply tests' monkeypatch seams keep working.
"""
from __future__ import annotations

import logging
from typing import Any

import job_agent.auto_apply as _pkg
from job_agent.auto_apply.driver import (
    _build_apply_qa,
    _fill_generic,
    _fill_linkedin,
    _fill_standard_ats,
)
from job_agent.auto_apply.eligibility import evaluate_apply_candidate
from job_agent.auto_apply.session_types import ApplyMode
from job_agent.auto_apply.session_types import ApplyEvent, ApplyResult

logger = logging.getLogger(__name__)


def fill_form(session: Any, page: Any, candidate: Any, ats: str) -> tuple[bool, str]:
    """Fill the application form. Returns (success, summary)."""
    profile = session._profile()
    qa = _build_apply_qa(profile, candidate.packet.qa_answers or {})
    cv_path = candidate.packet.tailored_cv_pdf_path or ""
    cover_md = candidate.packet.cover_letter_md or ""

    if ats == "linkedin":
        return _fill_linkedin(page, qa, cv_path, cover_md)
    if ats in ("greenhouse", "lever", "ashby", "recruitee", "smartrecruiters"):
        return _fill_standard_ats(page, qa, cv_path, cover_md)
    return _fill_generic(page, qa, cv_path, cover_md)


def get_profile(session: Any) -> Any:
    """Load candidate profile (cached on the session object)."""
    if not hasattr(session, "_profile_cache"):
        try:
            from job_agent.validators import load_profile_bundle
            profile, _, _ = load_profile_bundle(session.config)
            session._profile_cache = profile
        except Exception:
            session._profile_cache = None  # cache holds an Optional profile
    return session._profile_cache


def load_candidates(session: Any) -> list:
    candidates = _pkg.get_ready_candidates(min_score=session.min_score, limit=session.limit)
    if session.job_ids is not None:
        allowed = set(session.job_ids)
        candidates = [c for c in candidates if c.job.id in allowed]
    if session.mode == ApplyMode.FULL_AUTO:
        filtered = []
        for candidate in candidates:
            result = evaluate_apply_candidate(candidate, config=session.config, mode=session.mode)
            if result.eligible:
                filtered.append(candidate)
                continue
            session._emit(ApplyEvent(
                "progress",
                job_id=candidate.job.id,
                packet_id=candidate.packet.id,
                message=f"Skipping full-auto ineligible job: {', '.join(result.reasons)}",
                data={"eligibility": result.to_dict()},
            ))
        candidates = filtered
    return candidates


def mark_submitted(session: Any, candidate: Any) -> None:
    from job_agent.db.database import Database
    from job_agent.schemas.job import JobStatus
    from job_agent.schemas.packet import PacketStatus

    db = Database(session.config.db_path)
    db.initialize()
    db.update_job_status(candidate.job.id, JobStatus.MANUALLY_SUBMITTED)
    for pkt in db.get_packets_for_job(candidate.job.id):
        if pkt.id == candidate.packet.id:
            pkt.status = PacketStatus.MANUALLY_SUBMITTED
            db.save_packet(pkt)
            break
    db.log_event(
        candidate.job.id,
        "MANUALLY_SUBMITTED",
        {"packet_id": candidate.packet.id, "note": "Auto-apply session"},
        packet_id=candidate.packet.id,
    )
    try:
        from job_agent.exporters.internship_workbook import export_applied_internships
        export_applied_internships(session.config)
    except Exception as exc:
        logger.warning("Excel export after submit: %s", exc)


def mark_needs_manual(session: Any, candidate: Any, reason: str) -> None:
    """Flag a job for manual apply (full-auto hit a wall). The prepared packet
    is left intact as the ready-to-submit draft."""
    from job_agent.db.database import Database
    from job_agent.schemas.job import JobStatus

    db = Database(session.config.db_path)
    db.initialize()
    db.update_job_status(candidate.job.id, JobStatus.NEEDS_MANUAL)
    db.log_event(
        candidate.job.id,
        "NEEDS_MANUAL",
        {"packet_id": candidate.packet.id, "reason": reason, "note": "Full-auto hand-off"},
        packet_id=candidate.packet.id,
    )


def queue_needs_manual(session: Any, candidate: Any, summary: str, reason: str) -> ApplyResult:
    """Persist the hand-off, emit an event, and return a needs_manual result.
    The session loop keeps going — full-auto never blocks on a wall."""
    job = candidate.job
    packet = candidate.packet
    label = f"{job.title} @ {job.company}"
    persisted = True
    persist_error = ""
    try:
        session._mark_needs_manual(candidate, reason)
    except Exception as exc:  # persistence must not abort the run...
        # ...but it must not be reported as a clean hand-off either. The job
        # would otherwise vanish: not submitted, and not in the manual queue.
        # Keep going (never block) while surfacing the failure loudly.
        persisted = False
        persist_error = str(exc)
        logger.error("Could not persist needs_manual for %s: %s", label, exc, exc_info=True)
    if persisted:
        session._emit(ApplyEvent(
            "needs_manual",
            job_id=job.id,
            packet_id=packet.id,
            message=f"{label} needs manual apply ({reason}). Draft saved; continuing.",
            summary=summary,
            data={"reason": reason},
        ))
        return ApplyResult(
            job.id, packet.id, "needs_manual",
            f"{label}: {reason} — draft queued for manual apply.",
        )
    # Persistence failed: emit an error event and return an error status so the
    # dashboard shows the job needs attention rather than silently dropping it.
    session._emit(ApplyEvent(
        "error",
        job_id=job.id,
        packet_id=packet.id,
        message=(
            f"{label} hit a wall ({reason}) but the manual-queue write FAILED "
            f"({persist_error}). Apply manually — it is NOT queued."
        ),
        summary=summary,
        data={"reason": reason, "persist_error": persist_error},
    ))
    return ApplyResult(
        job.id, packet.id, "error",
        f"{label}: {reason} — manual-queue write failed ({persist_error}). Not queued.",
    )
