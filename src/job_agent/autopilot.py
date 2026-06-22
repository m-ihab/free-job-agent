"""Autonomous job-hunting loop.

When enabled, the autopilot runs on a thread and periodically:

1. Pulls fresh listings from configured sources (France Travail + free
   multi-source aggregators).
2. Deduplicates against the local database.
3. Scores each new job against the user's profile.
4. For high-fit jobs, auto-generates an application packet so the tailored
   CV/cover letter is ready when the user wakes up.

Everything stays local. No network actions are taken on the user's behalf
(no submissions, no logins, no scraping behind paywalls). The loop is stop/
start from the dashboard.

The heavy per-cycle logic lives in sibling modules so this file stays small:
  * :mod:`job_agent.autopilot_config` — config + runtime-state dataclasses
  * :mod:`job_agent.autopilot_sources` — the CAC40 ATS slug table
  * :mod:`job_agent.autopilot_cycle` — one cycle: search + sweep + summary
  * :mod:`job_agent.autopilot_packets` — packet tailoring + auto-apply trigger
  * :mod:`job_agent.autopilot_queries` — smart query expansion

Those modules reach the collaborators below through this module object
(``import job_agent.autopilot as ap``), so the names imported here are the
single monkeypatch seam the autopilot tests target.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

# These collaborators are imported here *so the sibling autopilot_* modules can
# reach them as ``ap.<name>`` and the tests can monkeypatch this one seam*.
# They look unused to ruff because the references live in the sibling modules.
from job_agent.ai_agent import suggest_search_queries  # noqa: F401  (monkeypatch seam)
from job_agent.config import AppConfig
from job_agent.db.database import Database  # noqa: F401  (monkeypatch seam)
from job_agent.intake.free_apis import (  # noqa: F401  (monkeypatch seam)
    KEYWORD_ONLY_SOURCES,
    FreeApiError,
    search_all_free_sources,
    search_free_api_jobs,
)
from job_agent.intake.france_market import (  # noqa: F401  (monkeypatch seam)
    expand_france_search_queries,
    expand_role_family,
)
from job_agent.notifier import notify_packet_ready  # noqa: F401  (monkeypatch seam)
from job_agent.pipeline import add_job_to_tracker, generate_packet_for_job  # noqa: F401  (seam)
from job_agent.tracker import ApplicationTracker  # noqa: F401  (monkeypatch seam)
from job_agent.validators import load_profile_bundle  # noqa: F401  (monkeypatch seam)

from job_agent.autopilot_config import AutopilotConfig, AutopilotState
from job_agent.autopilot_sources import CAC40_ATS_SLUGS

__all__ = [
    "Autopilot",
    "AutopilotConfig",
    "AutopilotState",
    "CAC40_ATS_SLUGS",
    "get_autopilot",
]


class Autopilot:
    """Thread-based autonomous loop. One instance per UI server is enough."""

    def __init__(self, config: AppConfig, autopilot_config: AutopilotConfig | None = None):
        self.config = config
        self.opts = autopilot_config or AutopilotConfig()
        self.state = AutopilotState()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ---- Lifecycle ----

    def start(self, options: AutopilotConfig | None = None) -> AutopilotState:
        with self._lock:
            if self.state.running:
                return self.state
            if options is not None:
                self.opts = options
            self._stop_event.clear()
            self.state = AutopilotState(running=True, started_at=_now_iso(), queries_count=len(self.opts.queries))
            self._thread = threading.Thread(target=self._loop, name="job-agent-autopilot", daemon=True)
            self._thread.start()
            return self.state

    def stop(self, wait: bool = False) -> AutopilotState:
        with self._lock:
            if not self.state.running:
                return self.state
            self._stop_event.set()
            self.state.running = False
            thread = self._thread
        if wait and thread is not None:
            thread.join(timeout=5)
        return self.state

    def status(self) -> dict[str, Any]:
        return {
            "running": self.state.running,
            "last_run_at": self.state.last_run_at,
            "last_error": self.state.last_error,
            "cycles_completed": self.state.cycles_completed,
            "jobs_added_total": self.state.jobs_added_total,
            "packets_built_total": self.state.packets_built_total,
            "last_summary": self.state.last_summary,
            "started_at": self.state.started_at,
            "queries_count": self.state.queries_count,
            "config": {
                "queries": self.opts.queries,
                "location": self.opts.location,
                "language": self.opts.language,
                "interval_minutes": self.opts.interval_minutes,
                "auto_packet_threshold": self.opts.auto_packet_threshold,
                "multi_source_limit": self.opts.multi_source_limit,
                "france_travail_limit": self.opts.france_travail_limit,
                "radius_km": self.opts.radius_km,
                "min_relevance": self.opts.min_relevance,
                "france_eu_only": self.opts.france_eu_only,
                "use_france_travail": self.opts.use_france_travail,
                "use_multi_source": self.opts.use_multi_source,
                "max_packets_per_cycle": self.opts.max_packets_per_cycle,
                "contract_type": self.opts.contract_type,
                "email_notify": self.opts.email_notify,
                "auto_apply": self.opts.auto_apply,
                "auto_apply_mode": self.opts.auto_apply_mode,
                "auto_apply_min_score": self.opts.auto_apply_min_score,
            },
        }

    # ---- Loop body ----

    def _loop(self) -> None:
        # First cycle runs immediately, then wait between runs.
        while True:
            try:
                summary = self._run_cycle()
                self.state.last_summary = summary
                self.state.last_run_at = _now_iso()
                self.state.cycles_completed += 1
                self.state.last_error = None
            except Exception as exc:  # pragma: no cover - safety net
                self.state.last_error = f"{type(exc).__name__}: {exc}"
            wait_seconds = max(60, int(self.opts.interval_minutes * 60))
            # Sleep in short increments so stop() responds quickly.
            slept = 0
            while slept < wait_seconds and not self._stop_event.is_set():
                time.sleep(min(5, wait_seconds - slept))
                slept += 5
            if self._stop_event.is_set():
                return

    def _france_travail_ready(self) -> bool:
        import os
        return bool(os.environ.get("FRANCE_TRAVAIL_CLIENT_ID") and os.environ.get("FRANCE_TRAVAIL_CLIENT_SECRET"))

    def _run_cycle(self) -> dict[str, Any]:
        # Delegated to keep this module small; imported lazily to avoid a
        # circular import at module load (the cycle module imports this one).
        from job_agent.autopilot_cycle import run_cycle
        return run_cycle(self)

    def _planned_queries(self) -> list[str]:
        from job_agent.autopilot_queries import plan_queries
        return plan_queries(self)


_EXPECTED_NOISE_PATTERNS = (
    "404", "not found", "410", "gone", "no such board", "board not found",
)


def _is_expected_noise(message: str) -> bool:
    """Return True for errors the user doesn't need to see (dead boards)."""
    lower = (message or "").casefold()
    return any(pattern in lower for pattern in _EXPECTED_NOISE_PATTERNS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_GLOBAL_AUTOPILOT: Autopilot | None = None


def get_autopilot(config: AppConfig) -> Autopilot:
    """Return a process-wide singleton autopilot, creating it on first call."""
    global _GLOBAL_AUTOPILOT
    if _GLOBAL_AUTOPILOT is None:
        _GLOBAL_AUTOPILOT = Autopilot(config)
    return _GLOBAL_AUTOPILOT
