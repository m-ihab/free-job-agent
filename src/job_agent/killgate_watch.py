"""JobSignal kill-gate watch: has HiringCafe shipped saved-search alerts?

MASTER-VERDICT §5 (money-engine): JobSignal B2C "dies the day HiringCafe ships
saved-search alerts". This module automates that watch: fetch public pages,
scan for alert-feature keywords, diff against the previous run's baseline, and
trip only on NEW hits on a primary source. Chatter sources (public Reddit
search JSON) only ever raise an "investigate" flag.

First run establishes a baseline without tripping (a keyword already present
today is not a launch signal — the gate watches for change). Run weekly via
cron/Task Scheduler through ``scripts/killgate_watch.py``; exit code 2 = gate
tripped, 0 otherwise.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; FreeJobAgent/0.3; market-watch; contact: local)"

KEYWORDS: tuple[str, ...] = (
    "saved search",
    "search alert",
    "job alert",
    "job alerts",
    "email alert",
    "email alerts",
    "notify me",
    "get notified",
    "daily digest",
    "weekly digest",
)


@dataclass(frozen=True)
class WatchSource:
    url: str
    kind: str  # primary | chatter


DEFAULT_SOURCES: tuple[WatchSource, ...] = (
    WatchSource("https://hiring.cafe", "primary"),
    WatchSource(
        "https://www.reddit.com/search.json?q=%22hiring.cafe%22+alerts&sort=new&limit=25",
        "chatter",
    ),
)


@dataclass(frozen=True)
class SourceCheck:
    url: str
    kind: str
    ok: bool
    hits: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class WatchReport:
    tripped: bool
    investigate: tuple[str, ...] = ()  # chatter URLs with new hits
    new_hits: dict[str, tuple[str, ...]] = field(default_factory=dict)
    baseline_established: bool = False
    checks: tuple[SourceCheck, ...] = ()


def state_path() -> Path:
    base = Path(os.environ.get("JOB_AGENT_DATA_DIR") or ".job_agent").expanduser()
    return base / "killgate_state.json"


def scan_hits(text: str) -> tuple[str, ...]:
    lowered = (text or "").lower()
    return tuple(sorted(keyword for keyword in KEYWORDS if keyword in lowered))


def check_source(source: WatchSource, *, timeout: int = 20) -> SourceCheck:
    from job_agent.utils.net import safe_get

    try:
        response = safe_get(source.url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        if response.status_code >= 400:
            return SourceCheck(source.url, source.kind, ok=False, error=f"http {response.status_code}")
        return SourceCheck(source.url, source.kind, ok=True, hits=scan_hits(response.text or ""))
    except Exception as exc:
        return SourceCheck(source.url, source.kind, ok=False, error=f"{type(exc).__name__}: {exc}")


def _load_state(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_state(path: Path, checks: tuple[SourceCheck, ...]) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "hits": {check.url: list(check.hits) for check in checks if check.ok},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("could not persist kill-gate state: %s", exc)


def run_watch(
    sources: tuple[WatchSource, ...] = DEFAULT_SOURCES,
    *,
    state_file: Path | None = None,
    timeout: int = 20,
) -> WatchReport:
    """One watch pass: check sources, diff vs baseline, persist new baseline."""
    path = state_file or state_path()
    previous = _load_state(path)
    baseline_known: dict[str, list[str]] = (previous or {}).get("hits", {})
    checks = tuple(check_source(source, timeout=timeout) for source in sources)

    new_hits: dict[str, tuple[str, ...]] = {}
    for check in checks:
        if not check.ok:
            continue
        fresh = tuple(hit for hit in check.hits if hit not in set(baseline_known.get(check.url, [])))
        if fresh:
            new_hits[check.url] = fresh

    first_run = previous is None
    tripped = False
    investigate: list[str] = []
    if not first_run:
        for check in checks:
            if check.url in new_hits:
                if check.kind == "primary":
                    tripped = True
                else:
                    investigate.append(check.url)
    _save_state(path, checks)
    return WatchReport(
        tripped=tripped,
        investigate=tuple(investigate),
        new_hits=new_hits,
        baseline_established=first_run,
        checks=checks,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exit 2 when the kill-gate trips, 0 otherwise."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = run_watch()
    for check in report.checks:
        if check.ok:
            logger.info("checked %s (%s): hits=%s", check.url, check.kind, list(check.hits) or "none")
        else:
            logger.warning("check failed %s: %s", check.url, check.error)
    if report.baseline_established:
        logger.info("baseline established — future runs alert only on NEW hits")
    if report.investigate:
        logger.warning("chatter mentions HiringCafe alerts — investigate: %s", ", ".join(report.investigate))
    if report.tripped:
        logger.error("KILL-GATE TRIPPED: HiringCafe primary source shows new alert-feature "
                     "keywords %s — re-read MASTER-VERDICT §5 before building more JobSignal",
                     report.new_hits)
        return 2
    logger.info("kill-gate quiet — JobSignal wedge still open")
    return 0
