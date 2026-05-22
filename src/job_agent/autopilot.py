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
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from job_agent.ai_agent import suggest_search_queries
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.intake.free_apis import (
    KEYWORD_ONLY_SOURCES,
    FreeApiError,
    search_all_free_sources,
    search_free_api_jobs,
)
from job_agent.intake.france_market import expand_france_search_queries
from job_agent.intake.france_travail_auth import france_travail_token
from job_agent.pipeline import add_job_to_tracker, generate_packet_for_job
from job_agent.schemas.job import JobStatus
from job_agent.tracker import ApplicationTracker
from job_agent.validators import load_profile_bundle


@dataclass
class AutopilotConfig:
    queries: list[str] = field(default_factory=lambda: [
        "data scientist", "data science", "machine learning",
        "data analyst", "data engineer",
    ])
    location: str = "Paris"
    language: str = "both"
    interval_minutes: int = 30
    auto_packet_threshold: int = 75
    multi_source_limit: int = 5
    france_travail_limit: int = 8
    use_france_travail: bool = True
    use_multi_source: bool = True
    max_packets_per_cycle: int = 5
    internships_only: bool = True


@dataclass
class AutopilotState:
    running: bool = False
    last_run_at: str | None = None
    last_error: str | None = None
    cycles_completed: int = 0
    jobs_added_total: int = 0
    packets_built_total: int = 0
    last_summary: dict[str, Any] | None = None
    started_at: str | None = None
    queries_count: int = 0


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
                "use_france_travail": self.opts.use_france_travail,
                "use_multi_source": self.opts.use_multi_source,
                "max_packets_per_cycle": self.opts.max_packets_per_cycle,
                "internships_only": self.opts.internships_only,
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
        db = Database(self.config.db_path)  # type: ignore[arg-type]
        db.initialize()
        tracker = ApplicationTracker(db)
        added: list[str] = []
        packets: list[str] = []
        errors: list[str] = []
        per_query: dict[str, int] = {}

        ft_ready = self.opts.use_france_travail and self._france_travail_ready()
        search_queries = self._planned_queries()
        for query in search_queries:
            if self._stop_event.is_set():
                break
            cycle_added = 0
            if ft_ready:
                try:
                    france_jobs = search_free_api_jobs(
                        "francetravail",
                        query=query,
                        location=self.opts.location,
                        limit=self.opts.france_travail_limit,
                        internships_only=self.opts.internships_only,
                        use_cache=True,
                        cache_ttl_hours=2.0,
                    )
                    for job in france_jobs:
                        tracked, created = add_job_to_tracker(self.config, job)
                        if created:
                            added.append(tracked.id)
                            cycle_added += 1
                except FreeApiError as exc:
                    errors.append(f"francetravail/{query}: {exc}")
                except Exception as exc:
                    errors.append(f"francetravail/{query}: {type(exc).__name__}: {exc}")

            if self.opts.use_multi_source:
                try:
                    multi = search_all_free_sources(
                        query=query,
                        location=self.opts.location,
                        limit_per_source=self.opts.multi_source_limit,
                        sources=list(KEYWORD_ONLY_SOURCES),
                        internships_only=self.opts.internships_only,
                        use_cache=True,
                        cache_ttl_hours=2.0,
                    )
                    for job in multi.get("jobs", []):
                        tracked, created = add_job_to_tracker(self.config, job)
                        if created:
                            added.append(tracked.id)
                            cycle_added += 1
                    for source, err in (multi.get("errors") or {}).items():
                        errors.append(f"{source}/{query}: {err[:120]}")
                except Exception as exc:
                    errors.append(f"multi/{query}: {type(exc).__name__}: {exc}")
            per_query[query] = cycle_added

        # Auto-tailor for high-fit jobs (newly added or recently scored).
        packets_built = 0
        for job_id in added:
            if packets_built >= self.opts.max_packets_per_cycle:
                break
            try:
                packet = generate_packet_for_job(self.config, job_id, force=False)
                # Only count "real" packets — if the score is below threshold
                # the job moves to SCORED status but we still generate a packet
                # via the existing flow (no separate gate). Track high-fit ones.
                if packet.fit_score is not None and packet.fit_score >= self.opts.auto_packet_threshold:
                    packets.append(packet.id)
                    packets_built += 1
            except Exception as exc:
                errors.append(f"packet/{job_id[:8]}: {type(exc).__name__}: {exc}")

        self.state.jobs_added_total += len(added)
        self.state.packets_built_total += packets_built
        return {
            "jobs_added": len(added),
            "packets_built": packets_built,
            "errors": errors[:10],
            "per_query": per_query,
            "queries": search_queries,
            "france_travail_used": ft_ready,
            "multi_source_used": self.opts.use_multi_source,
            "ran_at": _now_iso(),
        }

    def _planned_queries(self) -> list[str]:
        """Use local AI to expand the user's seeds, then dedupe conservatively."""
        planned: list[str] = []
        try:
            profile, master_cv, _ = load_profile_bundle(self.config)
            for seed in self.opts.queries:
                plan = suggest_search_queries(
                    profile,
                    master_cv,
                    seed_query=seed,
                    location=self.opts.location,
                    language=self.opts.language,
                    internships_only=self.opts.internships_only,
                    limit=4,
                )
                for query in plan.get("queries", []):
                    key = str(query).casefold().strip()
                    if key and key not in {item.casefold() for item in planned}:
                        planned.append(str(query).strip())
                if len(planned) >= 12:
                    break
        except Exception:
            planned = []
        if not planned:
            for seed in self.opts.queries:
                for query in expand_france_search_queries(seed, limit=4, language=self.opts.language):
                    key = query.casefold().strip()
                    if key and key not in {item.casefold() for item in planned}:
                        planned.append(query)
                    if len(planned) >= 12:
                        break
        return planned[:12] or self.opts.queries


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_GLOBAL_AUTOPILOT: Autopilot | None = None


def get_autopilot(config: AppConfig) -> Autopilot:
    """Return a process-wide singleton autopilot, creating it on first call."""
    global _GLOBAL_AUTOPILOT
    if _GLOBAL_AUTOPILOT is None:
        _GLOBAL_AUTOPILOT = Autopilot(config)
    return _GLOBAL_AUTOPILOT
