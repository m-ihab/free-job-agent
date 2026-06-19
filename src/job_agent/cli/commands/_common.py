"""Shared CLI utilities for free-job-agent command modules.

This module holds the console object, the ``CLIError`` type, configuration
helpers, and small printing/lookup utilities that several command modules
reuse. It intentionally depends only on real source modules (never on the
command modules or on ``cli.main``) so it can be imported freely without
introducing import cycles.
"""
from __future__ import annotations

import shutil
from pathlib import Path

try:  # pragma: no cover - optional pretty output
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except Exception:  # pragma: no cover
    class Console:
        def print(self, *args, **kwargs):
            print(*[str(a) for a in args])

    class Table:
        def __init__(self, title: str | None = None, *cols, **kwargs):
            self.title = title
            self.cols = list(cols)
            self.rows: list[tuple[str, ...]] = []

        def add_column(self, name, *args, **kwargs):
            self.cols.append(name)

        def add_row(self, *values):
            self.rows.append(tuple(str(v) for v in values))

        def __str__(self):
            lines = [self.title or ""] if self.title else []
            if self.cols:
                lines.append(" | ".join(map(str, self.cols)))
            lines.extend(" | ".join(row) for row in self.rows)
            return "\n".join(lines)

    class Panel:
        def __init__(self, text, title: str | None = None):
            self.text = text
            self.title = title

        def __str__(self):
            return f"{self.title or ''}\n{self.text}"

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.fingerprint import set_fingerprint
from job_agent.normalizer import normalize
from job_agent.tracker import ApplicationTracker
from job_agent.validators import load_profile_bundle

console = Console()


class CLIError(Exception):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _load_config() -> AppConfig:
    return AppConfig.load()


def _get_tracker(config: AppConfig) -> ApplicationTracker:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    return ApplicationTracker(db)


def _load_profiles(config: AppConfig):
    try:
        return load_profile_bundle(config)
    except Exception as exc:
        console.print(f"Warning: {exc}")
        return None, None, None


def _fail(message: str, code: int = 1) -> None:
    raise CLIError(message, code=code)


def _add_job(job, config: AppConfig) -> None:
    tracker = _get_tracker(config)
    job = normalize(job)
    job = set_fingerprint(job)
    existing = tracker.db.get_job_by_fingerprint(job.fingerprint)
    if existing:
        console.print(f"Duplicate detected. Job already exists: {existing.id}")
        return
    tracker.add_job(job)
    console.print(f"Added job {job.id[:8]} - {job.title} @ {job.company}")


def _find_examples_dir(config: AppConfig) -> Path:
    candidates = [
        config.examples_dir,
        Path.cwd() / "examples",
        Path(__file__).resolve().parents[4] / "examples",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise FileNotFoundError(
        "Could not find examples directory. Run from the repo root or set examples_dir in config.json."
    )


def _print_full_job_links(jobs) -> None:
    """Print full, copyable result URLs after Rich tables.

    Rich tables are easier to scan, but terminals often truncate long links.
    Keeping a plain-text block here makes the CLI useful for direct copy/paste.
    """
    rows: list[tuple[int, str, str, str]] = []
    for idx, job in enumerate(jobs, start=1):
        url = job.apply_url or job.source_url
        if not url:
            continue
        rows.append((idx, job.title, job.company, url))
    if not rows:
        return

    print()
    print("Full URLs:")
    for idx, title, company, url in rows:
        print(f"{idx}. {title} @ {company}")
        print(f"   {url}")


def _find_local_tool(name: str) -> str | None:
    appdata = Path.home() / "AppData" / "Roaming"
    local = Path.home() / "AppData" / "Local"
    program_files = Path("C:/Program Files")
    candidates = {
        "perl": [
            Path("C:/Strawberry/perl/bin/perl.exe"),
            Path("C:/Perl64/bin/perl.exe"),
            Path("C:/Perl/bin/perl.exe"),
        ],
        "node": [
            program_files / "nodejs" / "node.exe",
        ],
        "npm": [
            program_files / "nodejs" / "npm.cmd",
            appdata / "npm" / "npm.cmd",
        ],
        "openclaw": [
            appdata / "npm" / "openclaw.cmd",
            appdata / "npm" / "openclaw.ps1",
            local / "Programs" / "openclaw" / "openclaw.exe",
        ],
    }.get(name, [])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which(name)


_WIZARD_STEPS = [
    ("school", "School / university", "DSTI School of Engineering"),
    ("program", "Program / degree", "Applied MSc in Data Science & AI"),
    ("availability", "Earliest internship start date", "ASAP, end-of-studies 6-month stage"),
    ("duration", "Preferred internship duration", "6 months"),
    ("alternance_rhythm", "Alternance rhythm if relevant", "3 weeks company / 1 week school"),
    ("french_level", "French level (A1/A2/B1/B2/C1/C2)", "A2 (targeting B1)"),
    ("english_level", "English level (A1/A2/B1/B2/C1/C2/Fluent)", "Fluent"),
    ("work_auth", "Work authorization status in France", "Manual completion required before application submission."),
    ("visa_sponsorship", "Do you need visa sponsorship?", "Manual completion required before application submission."),
    ("convention", "Can your school provide a convention de stage?", "Manual completion required before application submission."),
    ("relocation", "Open to relocation outside Paris?", "No"),
    ("remote_preference", "Remote / hybrid / onsite preference", "Hybrid in Paris; remote within France OK"),
]
