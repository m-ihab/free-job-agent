"""Apply modes, events, the session state machine, and the module-level API.

This module owns the auto-apply session lifecycle and the single copy of the
module-level singleton state shared with the dashboard server. It imports the
detection helpers from :mod:`detect` and the Playwright driver helpers from
:mod:`driver`.
"""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import job_agent.auto_apply as _pkg
from job_agent.auto_apply.detect import (
    _detect_ats,
    _detect_human_wall,
    _is_france_travail_detail,
)
from job_agent.auto_apply.driver import (
    _PlaywrightNotInstalled,
    _build_apply_qa,
    _check_playwright,
    _click_postuler,
    _fill_generic,
    _fill_linkedin,
    _fill_standard_ats,
    _launch_browser_context,
    _select_browser_profile,
)

logger = logging.getLogger(__name__)


# ── Enums / DTOs ─────────────────────────────────────────────────────────────


class ApplyMode(str, Enum):
    FILL_AND_CONFIRM = "fill_and_confirm"
    FULL_AUTO = "full_auto"


@dataclass
class ApplyEvent:
    kind: str  # progress | pending_confirm | needs_manual | result | done | error
    job_id: str = ""
    packet_id: str = ""
    message: str = ""
    summary: str = ""
    screenshot_b64: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class ApplyResult:
    job_id: str
    packet_id: str
    status: str  # submitted | skipped | needs_manual | error
    message: str = ""


# ── Core session ──────────────────────────────────────────────────────────────


class AutoApplySession:
    """One session: iterates N candidates using Playwright."""

    def __init__(
        self,
        config: Any,
        mode: ApplyMode = ApplyMode.FILL_AND_CONFIRM,
        min_score: float = 70.0,
        limit: int = 10,
        headless: bool = False,
        job_ids: "list[str] | None" = None,
    ) -> None:
        self.config = config
        self.mode = mode
        self.min_score = min_score
        self.limit = limit
        self.headless = headless
        self.job_ids = job_ids  # if set, only apply to these job IDs

        self._progress_queue: queue.Queue[ApplyEvent] = queue.Queue()
        self._confirm_event = threading.Event()
        self._skip_flag = False
        self._cancel_flag = False
        self._running = False

    # ── Control interface ─────────────────────────────────────────────────────

    @property
    def progress_queue(self) -> "queue.Queue[ApplyEvent]":
        return self._progress_queue

    @property
    def running(self) -> bool:
        return self._running

    def confirm_submit(self) -> None:
        self._skip_flag = False
        self._confirm_event.set()

    def skip_current(self) -> None:
        self._skip_flag = True
        self._confirm_event.set()

    def cancel(self) -> None:
        self._cancel_flag = True
        self._confirm_event.set()

    def _reset_per_job_flags(self) -> None:
        """Reset per-job state so a skip/cancel on one job doesn't bleed into the next."""
        self._skip_flag = False

    def run_in_background(self) -> threading.Thread:
        t = threading.Thread(target=self._run, daemon=True, name="auto-apply")
        t.start()
        return t

    # ── Session loop ──────────────────────────────────────────────────────────

    def _emit(self, event: ApplyEvent) -> None:
        self._progress_queue.put(event)
        logger.info("[auto-apply] %s — %s", event.kind, event.message[:140])

    def _run(self) -> None:
        self._running = True
        results: list[ApplyResult] = []
        error_message: str | None = None
        try:
            _check_playwright()
            candidates = self._load_candidates()
            if not candidates:
                self._emit(ApplyEvent("done", message="No ready packets found. Run the autopilot or generate packets first."))
                return

            self._emit(ApplyEvent("progress", message=f"Found {len(candidates)} ready packet(s). Opening browser…"))

            # Location pre-flight — let the user see what they're about to apply to.
            _loc_lines = "; ".join(
                f"{c.job.title} @ {c.job.company} ({c.job.location or 'location unknown'})"
                for c in candidates[:6]
            )
            self._emit(ApplyEvent(
                "preflight",
                message=f"Applying to: {_loc_lines}",
                data={"count": len(candidates), "locations": [c.job.location for c in candidates]},
            ))

            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                profile = _select_browser_profile(self.config)
                if profile.warning:
                    self._emit(ApplyEvent("progress", message=profile.warning))
                self._emit(ApplyEvent(
                    "progress",
                    message=(
                        f"Using {profile.label} browser profile: {profile.path}. "
                        "If a login page appears, sign in once; Job Agent will reuse it next time."
                    ),
                ))
                ctx = _launch_browser_context(p, profile.path, self.headless)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()

                for i, candidate in enumerate(candidates, 1):
                    if self._cancel_flag:
                        break
                    self._reset_per_job_flags()
                    self._emit(ApplyEvent(
                        "progress",
                        job_id=candidate.job.id,
                        packet_id=candidate.packet.id,
                        message=f"[{i}/{len(candidates)}] {candidate.job.title} @ {candidate.job.company}",
                    ))
                    result = self._apply_one(page, candidate, i, len(candidates))
                    results.append(result)
                    self._emit(ApplyEvent(
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
            self._emit(ApplyEvent(
                "done",
                message=(
                    f"Session complete — submitted: {submitted} · skipped: {skipped} · "
                    f"needs manual: {needs_manual} · errors: {errors}"
                ),
                data={
                    "submitted": submitted,
                    "skipped": skipped,
                    "needs_manual": needs_manual,
                    "errors": errors,
                },
            ))
        except _PlaywrightNotInstalled as exc:
            error_message = str(exc)
            self._emit(ApplyEvent("error", message=str(exc)))
        except Exception as exc:
            logger.exception("Auto-apply session crashed")
            error_message = f"Session failed: {exc}"
            self._emit(ApplyEvent("error", message=error_message))
        finally:
            self._running = False
            _finish_session_state(results, error_message)

    def _apply_one(self, page: Any, candidate: Any, index: int, total: int) -> ApplyResult:
        job = candidate.job
        packet = candidate.packet
        label = f"{job.title} @ {job.company}"
        apply_url = job.apply_url or ""
        ats = _detect_ats(apply_url)

        try:
            self._emit(ApplyEvent(
                "progress", job_id=job.id, packet_id=packet.id,
                message=f"[{index}/{total}] {label} — navigating to {ats} form…",
            ))

            page.goto(apply_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2000)

            # France Travail detail pages show a "Postuler" button — click it
            # to reach the actual application form (external ATS or FT form).
            if _is_france_travail_detail(apply_url):
                ats = _click_postuler(page) or ats

            filled, summary = self._fill_form(page, candidate, ats)

            if not filled:
                if self.mode == ApplyMode.FULL_AUTO:
                    wall, reason = _detect_human_wall(page)
                    if wall:
                        return self._queue_needs_manual(candidate, summary, reason)
                return ApplyResult(job.id, packet.id, "error",
                                   f"Could not fill form for {label}: {summary}")

            # Gate before submit
            if self.mode == ApplyMode.FILL_AND_CONFIRM:
                screenshot = _pkg._screenshot_b64(page)
                self._emit(ApplyEvent(
                    "pending_confirm",
                    job_id=job.id,
                    packet_id=packet.id,
                    message=f"Form filled for {label}. Review and click Submit or Skip.",
                    summary=summary,
                    screenshot_b64=screenshot,
                ))
                self._confirm_event.clear()
                self._confirm_event.wait(timeout=300)
                if self._cancel_flag:
                    return ApplyResult(job.id, packet.id, "skipped", "Session cancelled.")
                if self._skip_flag:
                    return ApplyResult(job.id, packet.id, "skipped", f"Skipped {label}.")
            else:
                # FULL_AUTO — genuinely hands-off; the run never blocks. Detect
                # (never defeat) a human-presence wall and hand off to the manual
                # queue, otherwise submit straight away with no confirmation gate.
                if self._cancel_flag:
                    return ApplyResult(job.id, packet.id, "skipped", "Session cancelled.")
                wall, reason = _detect_human_wall(page)
                if wall:
                    return self._queue_needs_manual(candidate, summary, reason)

            # Submit
            self._emit(ApplyEvent("progress", job_id=job.id, packet_id=packet.id,
                                  message=f"[{index}/{total}] {label} — submitting…"))
            submitted = _pkg._click_submit(page, ats)
            if submitted:
                page.wait_for_timeout(3000)
                self._mark_submitted(candidate)
                return ApplyResult(job.id, packet.id, "submitted", f"Applied to {label}.")
            else:
                return ApplyResult(job.id, packet.id, "error",
                                   f"Submit button not found for {label}. Mark manually.")

        except Exception as exc:
            logger.warning("apply_one failed for %s: %s", label, exc, exc_info=True)
            return ApplyResult(job.id, packet.id, "error", f"Error on {label}: {exc}")

    # ── Form filling ──────────────────────────────────────────────────────────

    def _fill_form(self, page: Any, candidate: Any, ats: str) -> tuple[bool, str]:
        """Fill the application form. Returns (success, summary)."""
        profile = self._profile()
        qa = _build_apply_qa(profile, candidate.packet.qa_answers or {})
        cv_path = candidate.packet.tailored_cv_pdf_path or ""
        cover_md = candidate.packet.cover_letter_md or ""

        if ats == "linkedin":
            return _fill_linkedin(page, qa, cv_path, cover_md)
        if ats in ("greenhouse", "lever", "ashby", "recruitee", "smartrecruiters"):
            return _fill_standard_ats(page, qa, cv_path, cover_md)
        return _fill_generic(page, qa, cv_path, cover_md)

    def _profile(self) -> Any:
        """Load candidate profile (cached on the session object)."""
        if not hasattr(self, "_profile_cache"):
            try:
                from job_agent.validators import load_profile_bundle
                profile, _, _ = load_profile_bundle(self.config)
                self._profile_cache = profile
            except Exception:
                self._profile_cache = None
        return self._profile_cache

    def _load_candidates(self) -> list:
        candidates = _pkg.get_ready_candidates(min_score=self.min_score, limit=self.limit)
        if self.job_ids is not None:
            allowed = set(self.job_ids)
            candidates = [c for c in candidates if c.job.id in allowed]
        return candidates

    def _mark_submitted(self, candidate: Any) -> None:
        from job_agent.db.database import Database
        from job_agent.schemas.job import JobStatus
        from job_agent.schemas.packet import PacketStatus

        db = Database(self.config.db_path)
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
            export_applied_internships(self.config)
        except Exception as exc:
            logger.warning("Excel export after submit: %s", exc)

    def _mark_needs_manual(self, candidate: Any, reason: str) -> None:
        """Flag a job for manual apply (full-auto hit a wall). The prepared
        packet is left intact as the ready-to-submit draft."""
        from job_agent.db.database import Database
        from job_agent.schemas.job import JobStatus

        db = Database(self.config.db_path)
        db.initialize()
        db.update_job_status(candidate.job.id, JobStatus.NEEDS_MANUAL)
        db.log_event(
            candidate.job.id,
            "NEEDS_MANUAL",
            {"packet_id": candidate.packet.id, "reason": reason, "note": "Full-auto hand-off"},
            packet_id=candidate.packet.id,
        )

    def _queue_needs_manual(self, candidate: Any, summary: str, reason: str) -> ApplyResult:
        """Persist the hand-off, emit an event, and return a needs_manual result.
        The session loop keeps going — full-auto never blocks on a wall."""
        job = candidate.job
        packet = candidate.packet
        label = f"{job.title} @ {job.company}"
        try:
            self._mark_needs_manual(candidate, reason)
        except Exception as exc:  # persistence must not abort the run
            logger.warning("Could not mark %s needs_manual: %s", label, exc)
        self._emit(ApplyEvent(
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


def get_candidates_preview(min_score: float = 65.0, limit: int = 10) -> list[dict]:
    """Return a preview list of candidates that would be processed by auto-apply.

    Returns plain dicts safe for JSON serialisation.  No browser is opened.
    """
    candidates = _pkg.get_ready_candidates(min_score=min_score, limit=limit)
    return [
        {
            "job_id": c.job.id,
            "title": c.job.title,
            "company": c.job.company,
            "location": c.job.location or "",
            "apply_url": c.job.apply_url or "",
            "packet_id": c.packet.id,
            "fit_score": c.packet.fit_score,
        }
        for c in candidates
    ]


# ── Module-level singleton state (shared with server.py) ─────────────────────


_session_lock = threading.Lock()
_state: dict = {
    "running": False,
    "mode": "fill_and_confirm",
    "started_at": None,
    "results_count": {"submitted": 0, "skipped": 0, "errors": 0},
    "error": None,
}
_event_queue: queue.Queue[ApplyEvent] = queue.Queue()
_active: AutoApplySession | None = None


def get_state() -> dict:
    return dict(_state)


def get_event_queue() -> "queue.Queue[ApplyEvent]":
    return _event_queue


def _finish_session_state(results: list[ApplyResult], error_message: str | None = None) -> None:
    global _state
    submitted = sum(1 for r in results if r.status == "submitted")
    skipped = sum(1 for r in results if r.status == "skipped")
    errors = sum(1 for r in results if r.status == "error")
    if error_message:
        errors = max(errors, 1)
    with _session_lock:
        _state = {
            **_state,
            "running": False,
            "results_count": {"submitted": submitted, "skipped": skipped, "errors": errors},
            "error": error_message,
        }


def start(
    config: Any,
    mode: str,
    min_score: float,
    limit: int,
    job_ids: "list[str] | None" = None,
) -> dict:
    global _active, _state
    with _session_lock:
        if _state["running"]:
            return {"ok": False, "error": "A session is already running."}
        import datetime
        _state = {
            "running": True,
            "mode": mode,
            "started_at": datetime.datetime.now().isoformat(),
            "results_count": {"submitted": 0, "skipped": 0, "errors": 0},
            "error": None,
        }
        while not _event_queue.empty():
            try:
                _event_queue.get_nowait()
            except queue.Empty:
                break

        _active = AutoApplySession(
            config=config,
            mode=ApplyMode(mode),
            min_score=min_score,
            limit=limit,
            job_ids=job_ids if job_ids else None,
        )
        _active._progress_queue = _event_queue
        _active.run_in_background()
    return {"ok": True, "state": get_state()}


def open_browser_for_login(config: Any) -> dict:
    """Open the dedicated Job Agent browser profile so the user can log in.

    Launches the browser window in the foreground.  The user logs in to
    France Travail, LinkedIn, etc.  Closing the browser persists cookies in
    the dedicated profile directory for future sessions.
    """
    try:
        _check_playwright()
    except _PlaywrightNotInstalled as exc:
        return {"ok": False, "error": str(exc)}

    profile = _select_browser_profile(config)
    try:
        from playwright.sync_api import sync_playwright

        def _open() -> None:
            with sync_playwright() as p:
                ctx = _launch_browser_context(p, profile.path, headless=False)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto("https://candidat.francetravail.fr/espacepersonnel/", wait_until="domcontentloaded", timeout=15_000)
                logger.info("[auto-apply] login-setup browser opened at %s", profile.path)
                # Keep browser open until the user closes it
                try:
                    ctx.wait_for_event("close", timeout=0)
                except Exception:
                    pass

        t = threading.Thread(target=_open, daemon=True, name="login-setup")
        t.start()
        return {
            "ok": True,
            "profile_path": str(profile.path),
            "message": (
                "Browser opened with the Job Agent profile. "
                "Log in to France Travail and any other sites, then close the browser. "
                "Job Agent will reuse your session next time."
            ),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def confirm() -> dict:
    with _session_lock:
        if _active:
            _active.confirm_submit()
            return {"ok": True}
    return {"ok": False, "error": "No active session."}


def skip() -> dict:
    with _session_lock:
        if _active:
            _active.skip_current()
            return {"ok": True}
    return {"ok": False, "error": "No active session."}


def cancel() -> dict:
    with _session_lock:
        if _active:
            _active.cancel()
            return {"ok": True}
    return {"ok": False, "error": "No active session."}
