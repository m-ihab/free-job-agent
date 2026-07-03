"""Apply modes, events, the session state machine, and the module-level API.

This module owns the :class:`AutoApplySession` lifecycle. The heavy per-job
logic lives in sibling modules so the file stays small:
  * :mod:`job_agent.auto_apply.session_types` — ApplyMode / ApplyEvent / ApplyResult
  * :mod:`job_agent.auto_apply.session_runner` — the loop + per-job orchestration
  * :mod:`job_agent.auto_apply.session_actions` — form fill + DB hand-off writes
  * :mod:`job_agent.auto_apply.session_control` — singleton state + start/confirm/…

The class methods below stay as thin delegators so the auto-apply tests can keep
patching them on a live instance (``monkeypatch.setattr(sess, "_fill_form", …)``)
and so the runner's ``session._fill_form(…)`` call hits the patched version.
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any

from job_agent.auto_apply import session_actions, session_runner
from job_agent.auto_apply.session_types import ApplyEvent, ApplyMode, ApplyResult

logger = logging.getLogger(__name__)

# How long FILL_AND_CONFIRM waits for the user to click Submit/Skip before
# giving up on the job. Timing out must SKIP, never submit.
DEFAULT_CONFIRM_TIMEOUT_S = 300.0


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
        self.confirm_timeout_s: float = DEFAULT_CONFIRM_TIMEOUT_S

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

    def _emit(self, event: ApplyEvent) -> None:
        self._progress_queue.put(event)
        logger.info("[auto-apply] %s — %s", event.kind, event.message[:140])

    # ── Loop + per-job (delegated to sibling modules; kept as methods so tests
    #    can patch them on the instance) ───────────────────────────────────────

    def _run(self) -> None:
        session_runner.run(self)

    def _apply_one(self, page: Any, candidate: Any, index: int, total: int) -> ApplyResult:
        return session_runner.apply_one(self, page, candidate, index, total)

    def _fill_form(self, page: Any, candidate: Any, ats: str) -> tuple[bool, str]:
        return session_actions.fill_form(self, page, candidate, ats)

    def _profile(self) -> Any:
        return session_actions.get_profile(self)

    def _load_candidates(self) -> list:
        return session_actions.load_candidates(self)

    def _mark_submitted(self, candidate: Any) -> None:
        session_actions.mark_submitted(self, candidate)

    def _mark_needs_manual(self, candidate: Any, reason: str) -> None:
        session_actions.mark_needs_manual(self, candidate, reason)

    def _queue_needs_manual(self, candidate: Any, summary: str, reason: str) -> ApplyResult:
        return session_actions.queue_needs_manual(self, candidate, summary, reason)


# Module-level API + singleton state live in session_control; re-export so the
# historical paths (``from job_agent.auto_apply.session import start, …``) work.
from job_agent.auto_apply.session_control import (  # noqa: E402,F401  (re-export; after class to avoid cycle)
    _finish_session_state,
    cancel,
    confirm,
    get_candidates_preview,
    get_event_queue,
    get_state,
    open_browser_for_login,
    skip,
    start,
)

__all__ = [
    "ApplyMode",
    "ApplyEvent",
    "ApplyResult",
    "AutoApplySession",
    "get_candidates_preview",
    "get_state",
    "get_event_queue",
    "_finish_session_state",
    "start",
    "open_browser_for_login",
    "confirm",
    "skip",
    "cancel",
]
