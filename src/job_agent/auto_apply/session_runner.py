"""The auto-apply session loop and per-job orchestration.

These are free functions that take the :class:`AutoApplySession` as ``session``
and call its methods (``session._fill_form`` etc.) and the package-level driver
collaborators (``_pkg._click_submit`` etc.) — exactly the seams the auto-apply
tests monkeypatch, so behaviour is unchanged after the split.
"""
from __future__ import annotations

import logging
from typing import Any

import job_agent.auto_apply as _pkg
from job_agent.auto_apply.detect import (
    _detect_ats,
    _detect_human_wall,
    _is_france_travail_detail,
)
from job_agent.auto_apply.driver import (
    _PlaywrightNotInstalled,
    _check_playwright,
    _click_postuler,
    _launch_browser_context,
    _select_browser_profile,
)
from job_agent.auto_apply.session_types import ApplyEvent, ApplyMode, ApplyResult

logger = logging.getLogger(__name__)


def run(session: Any) -> None:
    session._running = True
    results: list[ApplyResult] = []
    error_message: str | None = None
    try:
        _check_playwright()
        candidates = session._load_candidates()
        if not candidates:
            session._emit(ApplyEvent("done", message="No ready packets found. Run the autopilot or generate packets first."))
            return

        session._emit(ApplyEvent("progress", message=f"Found {len(candidates)} ready packet(s). Opening browser…"))

        # Location pre-flight — let the user see what they're about to apply to.
        _loc_lines = "; ".join(
            f"{c.job.title} @ {c.job.company} ({c.job.location or 'location unknown'})"
            for c in candidates[:6]
        )
        session._emit(ApplyEvent(
            "preflight",
            message=f"Applying to: {_loc_lines}",
            data={"count": len(candidates), "locations": [c.job.location for c in candidates]},
        ))

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            profile = _select_browser_profile(session.config)
            if profile.warning:
                session._emit(ApplyEvent("progress", message=profile.warning))
            session._emit(ApplyEvent(
                "progress",
                message=(
                    f"Using {profile.label} browser profile: {profile.path}. "
                    "If a login page appears, sign in once; Job Agent will reuse it next time."
                ),
            ))
            ctx = _launch_browser_context(p, profile.path, session.headless)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            for i, candidate in enumerate(candidates, 1):
                if session._cancel_flag:
                    break
                session._reset_per_job_flags()
                session._emit(ApplyEvent(
                    "progress",
                    job_id=candidate.job.id,
                    packet_id=candidate.packet.id,
                    message=f"[{i}/{len(candidates)}] {candidate.job.title} @ {candidate.job.company}",
                ))
                result = session._apply_one(page, candidate, i, len(candidates))
                results.append(result)
                session._emit(ApplyEvent(
                    "result",
                    job_id=result.job_id,
                    packet_id=result.packet_id,
                    message=result.message,
                    data={"status": result.status},
                ))

            try:
                ctx.close()
            except Exception:
                logger.debug("[auto-apply] browser context close failed (already gone)", exc_info=True)

        submitted = sum(1 for r in results if r.status == "submitted")
        skipped = sum(1 for r in results if r.status == "skipped")
        needs_manual = sum(1 for r in results if r.status == "needs_manual")
        errors = sum(1 for r in results if r.status == "error")
        session._emit(ApplyEvent(
            "done",
            message=(
                f"Session complete — submitted: {submitted} · skipped: {skipped} · "
                f"needs manual: {needs_manual} · errors: {errors}"
            ),
            data={"submitted": submitted, "skipped": skipped, "needs_manual": needs_manual, "errors": errors},
        ))
    except _PlaywrightNotInstalled as exc:
        error_message = str(exc)
        session._emit(ApplyEvent("error", message=str(exc)))
    except Exception as exc:
        logger.exception("Auto-apply session crashed")
        error_message = f"Session failed: {exc}"
        session._emit(ApplyEvent("error", message=error_message))
    finally:
        session._running = False
        from job_agent.auto_apply.session_control import _finish_session_state
        _finish_session_state(results, error_message)


def apply_one(session: Any, page: Any, candidate: Any, index: int, total: int) -> ApplyResult:
    job = candidate.job
    packet = candidate.packet
    label = f"{job.title} @ {job.company}"
    apply_url = job.apply_url or ""
    ats = _detect_ats(apply_url)

    try:
        session._emit(ApplyEvent(
            "progress", job_id=job.id, packet_id=packet.id,
            message=f"[{index}/{total}] {label} — navigating to {ats} form…",
        ))

        page.goto(apply_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2000)

        # France Travail detail pages show a "Postuler" button — click it to
        # reach the actual application form (external ATS or FT form).
        if _is_france_travail_detail(apply_url):
            ats = _click_postuler(page) or ats

        filled, summary = session._fill_form(page, candidate, ats)

        if not filled:
            if session.mode == ApplyMode.FULL_AUTO:
                wall, reason = _detect_human_wall(page)
                if wall:
                    return session._queue_needs_manual(candidate, summary, reason)
            return ApplyResult(job.id, packet.id, "error", f"Could not fill form for {label}: {summary}")

        # Gate before submit
        if session.mode == ApplyMode.FILL_AND_CONFIRM:
            screenshot = _pkg._screenshot_b64(page)
            # Clear BEFORE emitting: a confirm landing the instant the prompt
            # appears must not be wiped by a late clear.
            session._confirm_event.clear()
            session._emit(ApplyEvent(
                "pending_confirm",
                job_id=job.id,
                packet_id=packet.id,
                message=f"Form filled for {label}. Review and click Submit or Skip.",
                summary=summary,
                screenshot_b64=screenshot,
            ))
            confirmed = session._confirm_event.wait(timeout=session.confirm_timeout_s)
            if session._cancel_flag:
                return ApplyResult(job.id, packet.id, "skipped", "Session cancelled.")
            if session._skip_flag:
                return ApplyResult(job.id, packet.id, "skipped", f"Skipped {label}.")
            if not confirmed:
                return ApplyResult(
                    job.id, packet.id, "skipped",
                    f"Skipped {label}: timed out after {session.confirm_timeout_s:.0f}s waiting for your confirmation.",
                )
        else:
            # FULL_AUTO — genuinely hands-off; the run never blocks. Detect
            # (never defeat) a human-presence wall and hand off to the manual
            # queue, otherwise submit straight away with no confirmation gate.
            if session._cancel_flag:
                return ApplyResult(job.id, packet.id, "skipped", "Session cancelled.")
            wall, reason = _detect_human_wall(page)
            if wall:
                return session._queue_needs_manual(candidate, summary, reason)

        # Submit
        session._emit(ApplyEvent("progress", job_id=job.id, packet_id=packet.id,
                                 message=f"[{index}/{total}] {label} — submitting…"))
        submitted = _pkg._click_submit(page, ats)
        if submitted:
            page.wait_for_timeout(3000)
            # A CAPTCHA / login / anti-bot wall commonly appears *after* the
            # submit click. In FULL_AUTO (no human watching) re-detect before
            # recording success — if a wall is now present, or detection failed
            # (fail-closed), hand off to the manual queue rather than falsely
            # marking the job submitted.
            if session.mode == ApplyMode.FULL_AUTO:
                wall_after, reason_after = _detect_human_wall(page)
                if wall_after:
                    return session._queue_needs_manual(candidate, summary, reason_after)
            session._mark_submitted(candidate)
            return ApplyResult(job.id, packet.id, "submitted", f"Applied to {label}.")
        return ApplyResult(job.id, packet.id, "error", f"Submit button not found for {label}. Mark manually.")

    except Exception as exc:
        logger.warning("apply_one failed for %s: %s", label, exc, exc_info=True)
        return ApplyResult(job.id, packet.id, "error", f"Error on {label}: {exc}")
