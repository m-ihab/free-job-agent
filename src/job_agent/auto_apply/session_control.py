"""Module-level auto-apply singleton state and the dashboard-facing API.

Owns the single session-state dict + event queue shared with the dashboard
server, plus the start/confirm/skip/cancel/preview entry points. ``start``
imports :class:`AutoApplySession` lazily so this module and the session facade
can import each other without a cycle.
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any

import job_agent.auto_apply as _pkg
from job_agent.auto_apply.driver import (
    _PlaywrightNotInstalled,
    _check_playwright,
    _launch_browser_context,
    _select_browser_profile,
)
from job_agent.auto_apply.session_types import ApplyEvent, ApplyMode, ApplyResult

logger = logging.getLogger(__name__)


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
_event_queue: "queue.Queue[ApplyEvent]" = queue.Queue()
_active: "Any | None" = None


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
    from job_agent.auto_apply.session import AutoApplySession

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
