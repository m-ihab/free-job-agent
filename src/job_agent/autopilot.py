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
from job_agent.intake.france_market import expand_france_search_queries, expand_role_family
from job_agent.intake.france_travail_auth import france_travail_token
from job_agent.notifier import notify_packet_ready
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
    radius_km: int = 25
    min_relevance: int = 50
    france_eu_only: bool = True
    use_france_travail: bool = True
    use_multi_source: bool = True
    use_cac40_sweep: bool = True
    cac40_limit_per_company: int = 3
    max_packets_per_cycle: int = 5
    internships_only: bool = True
    email_notify: bool = False


# Known CAC40 / large-French company ATS slugs. These are public job boards
# that don't need any credentials — we just point the existing Greenhouse /
# Lever / Ashby / SmartRecruiters / Workable / Recruitee fetchers at them.
# Any slug that ever stops working is harmless: per-source failures don't
# break the rest of the cycle.
CAC40_ATS_SLUGS: list[tuple[str, str, str]] = [
    # (source, slug, display name)
    ("greenhouse", "criteo", "Criteo"),
    ("greenhouse", "datadog", "Datadog"),
    ("greenhouse", "doctolib", "Doctolib"),
    ("greenhouse", "mistralai", "Mistral AI"),
    ("greenhouse", "huggingface", "Hugging Face"),
    ("greenhouse", "stripe", "Stripe"),
    ("greenhouse", "scaleway", "Scaleway"),
    ("greenhouse", "back-market", "Back Market"),
    ("greenhouse", "qonto", "Qonto"),
    ("greenhouse", "blablacar", "BlaBlaCar"),
    ("greenhouse", "alan", "Alan"),
    ("greenhouse", "swile", "Swile"),
    ("greenhouse", "spendesk", "Spendesk"),
    ("greenhouse", "shift-technology", "Shift Technology"),
    ("lever", "ledger", "Ledger"),
    ("lever", "mirakl", "Mirakl"),
    ("lever", "algolia", "Algolia"),
    ("ashby", "mistral", "Mistral"),
    ("smartrecruiters", "Capgemini", "Capgemini"),
    ("smartrecruiters", "AccorHotels", "Accor"),
    ("smartrecruiters", "LVMH", "LVMH"),
    ("smartrecruiters", "Veolia", "Veolia"),
    ("workable", "ledger", "Ledger"),
    ("recruitee", "spendesk", "Spendesk"),
]


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
                "radius_km": self.opts.radius_km,
                "min_relevance": self.opts.min_relevance,
                "france_eu_only": self.opts.france_eu_only,
                "use_france_travail": self.opts.use_france_travail,
                "use_multi_source": self.opts.use_multi_source,
                "max_packets_per_cycle": self.opts.max_packets_per_cycle,
                "internships_only": self.opts.internships_only,
                "email_notify": self.opts.email_notify,
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
                        min_relevance=self.opts.min_relevance,
                        france_eu_only=self.opts.france_eu_only,
                        radius_km=self.opts.radius_km,
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
                        min_relevance=self.opts.min_relevance,
                        france_eu_only=self.opts.france_eu_only,
                        radius_km=self.opts.radius_km,
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

        # CAC40 / large-FR ATS sweep — only data-friendly companies, slug list
        # is static so failure of one slug doesn't kill the cycle.
        cac40_added = 0
        if self.opts.use_cac40_sweep:
            for source_kind, slug, display_name in CAC40_ATS_SLUGS:
                if self._stop_event.is_set():
                    break
                try:
                    sweep_jobs = search_free_api_jobs(
                        source_kind,
                        query=self.opts.queries[0] if self.opts.queries else "data",
                        board=slug,
                        limit=self.opts.cac40_limit_per_company,
                        internships_only=self.opts.internships_only,
                        min_relevance=self.opts.min_relevance,
                        france_eu_only=self.opts.france_eu_only,
                        use_cache=True,
                        cache_ttl_hours=4.0,
                    )
                except FreeApiError as exc:
                    errors.append(f"{source_kind}/{display_name}: {exc}")
                    continue
                except Exception as exc:
                    errors.append(f"{source_kind}/{display_name}: {type(exc).__name__}: {exc}")
                    continue
                for job in sweep_jobs:
                    tracked, created = add_job_to_tracker(self.config, job)
                    if created:
                        added.append(tracked.id)
                        cac40_added += 1
            per_query["__cac40_sweep__"] = cac40_added

        # Auto-tailor for high-fit jobs (newly added or recently scored). The
        # AI fit cache (when available) acts as a second gate so weak-fit jobs
        # don't waste tailoring cycles.
        packets_built = 0
        ai_skipped = 0
        notifications: list[dict[str, Any]] = []
        for job_id in added:
            if packets_built >= self.opts.max_packets_per_cycle:
                break
            ai_cache = db.list_ai_cache_for_job(job_id) if db else {}
            ai_fit = (ai_cache or {}).get("fit") or {}
            if ai_fit.get("verdict") == "weak":
                ai_skipped += 1
                continue
            try:
                packet = generate_packet_for_job(self.config, job_id, force=False)
                if packet.fit_score is not None and packet.fit_score >= self.opts.auto_packet_threshold:
                    packets.append(packet.id)
                    packets_built += 1
                    if self.opts.email_notify:
                        job = db.resolve_job(job_id)
                        if job:
                            notifications.append(notify_packet_ready(self.config, job, packet, reason="Autopilot"))
            except Exception as exc:
                errors.append(f"packet/{job_id[:8]}: {type(exc).__name__}: {exc}")

        self.state.jobs_added_total += len(added)
        self.state.packets_built_total += packets_built
        return {
            "jobs_added": len(added),
            "packets_built": packets_built,
            "ai_skipped": ai_skipped,
            "notifications": notifications[:5],
            "errors": errors[:10],
            "per_query": per_query,
            "queries": search_queries,
            "france_travail_used": ft_ready,
            "multi_source_used": self.opts.use_multi_source,
            "ran_at": _now_iso(),
        }

    def _planned_queries(self) -> list[str]:
        """Smart query expansion: role-family + AI + bilingual fallback.

        Order of expansion (best-recall mix):
        1. ``expand_role_family`` — deterministic data/AI synonyms (works
           without Ollama; e.g. "data scientist" -> data engineer, ml
           engineer, ai engineer, data analyst).
        2. AI ``suggest_search_queries`` if Ollama is reachable.
        3. ``expand_france_search_queries`` bilingual stage/alternance pack
           so we always test French internship terms.
        """
        planned: list[str] = []

        def _add(query: str) -> None:
            key = (query or "").casefold().strip()
            if not key or len(query) > 70:
                return
            seen = {item.casefold() for item in planned}
            if key in seen:
                return
            planned.append(query.strip())

        # 1) Deterministic role-family expansion always runs.
        for seed in self.opts.queries:
            for sibling in expand_role_family(seed):
                _add(sibling)

        # 2) Local-AI plan when reachable.
        try:
            profile, master_cv, _ = load_profile_bundle(self.config)
            for seed in self.opts.queries[:3]:
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
                    _add(str(query))
        except Exception:
            pass

        # 3) French stage/alternance variants as the final safety net.
        for seed in self.opts.queries[:4]:
            for query in expand_france_search_queries(seed, limit=3, language=self.opts.language):
                _add(query)
                if len(planned) >= 18:
                    break
        # Hard cap so cycles stay reasonably fast.
        return planned[:18] or self.opts.queries


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_GLOBAL_AUTOPILOT: Autopilot | None = None


def get_autopilot(config: AppConfig) -> Autopilot:
    """Return a process-wide singleton autopilot, creating it on first call."""
    global _GLOBAL_AUTOPILOT
    if _GLOBAL_AUTOPILOT is None:
        _GLOBAL_AUTOPILOT = Autopilot(config)
    return _GLOBAL_AUTOPILOT
