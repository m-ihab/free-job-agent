"""Local-first CLI for free-job-agent.

This module intentionally uses the Python standard library for argument
parsing so the core workflow still works in environments where Click is not
available. Tests continue to use a tiny local ``click.testing`` shim.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import webbrowser
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
from job_agent.intake.discover import discover_job_links
from job_agent.intake.file import ingest_file
from job_agent.intake.free_apis import FreeApiError, search_free_api_jobs, supported_source_names
from job_agent.intake.france_market import (
    DEFAULT_FRANCE_DATA_AI_QUERIES,
    board_notes,
    build_france_search_urls,
    cac40_targets,
    expand_france_search_queries,
)
from job_agent.intake.paste import ingest_paste
from job_agent.intake.rss import ingest_rss
from job_agent.intake.url import ingest_url
from job_agent.normalizer import normalize
from job_agent.pipeline import add_job_to_tracker, generate_packet_for_job, process_file
from job_agent.schemas.job import JobStatus
from job_agent.schemas.packet import PacketStatus
from job_agent.scorer import score_job
from job_agent.tracker import ApplicationTracker
from job_agent.validators import load_profile_bundle, validate_profile_bundle

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
        Path(__file__).resolve().parents[3] / "examples",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise FileNotFoundError(
        "Could not find examples directory. Run from the repo root or set examples_dir in config.json."
    )


def _handle_init(args) -> None:
    config = AppConfig()
    config.ensure_dirs()
    config.save()
    Database(config.db_path).initialize()  # type: ignore[arg-type]
    console.print(f"Initialized job-agent data directory at: {config.data_dir}")
    console.print(f"Place profile files in: {config.profiles_dir}")


def _handle_copy_examples(args) -> None:
    config = AppConfig.load()
    config.ensure_dirs()
    try:
        src_dir = _find_examples_dir(config)
    except Exception as exc:
        _fail(str(exc))
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        dst = config.profiles_dir / name  # type: ignore[operator]
        src = src_dir / name
        if dst.exists():
            console.print(f"Exists, not overwriting: {dst}")
        else:
            shutil.copyfile(src, dst)
            console.print(f"Copied: {dst}")


def _handle_validate_profile(args) -> None:
    report = validate_profile_bundle(_load_config())
    if report.errors:
        console.print("Profile validation failed")
        for err in report.errors:
            console.print(f"  - {err}")
        _fail("Profile validation failed", code=1)
    console.print("Profile validation passed")
    for warning in report.warnings:
        console.print(f"Warning: {warning}")


def _handle_add_paste(args) -> None:
    console.print("Paste job description below. Press Ctrl+D (Ctrl+Z on Windows) when done:")
    text = sys.stdin.read()
    _add_job(ingest_paste(text, title=args.title or None, company=args.company or None, url=args.url or None), _load_config())


def _handle_add_file(args) -> None:
    _add_job(ingest_file(args.path, title=args.title or None, company=args.company or None, url=args.url or None), _load_config())


def _handle_add_url(args) -> None:
    try:
        job = ingest_url(args.url)
    except Exception as exc:
        _fail(f"Failed to fetch URL: {exc}")
    _add_job(job, _load_config())


def _handle_add_rss(args) -> None:
    config = _load_config()
    tracker = _get_tracker(config)
    jobs = ingest_rss(args.feed_url, limit=args.limit)
    added = 0
    for job in jobs:
        job = set_fingerprint(normalize(job))
        if tracker.db.get_job_by_fingerprint(job.fingerprint):
            continue
        tracker.add_job(job)
        added += 1
    console.print(f"Imported {added}/{len(jobs)} new jobs from RSS feed.")


def _handle_discover_links(args) -> None:
    try:
        links = discover_job_links(args.url, limit=args.limit)
    except Exception as exc:
        _fail(f"Failed to discover links: {exc}")
    if not links:
        console.print("No likely job links found.")
        return
    for link in links:
        console.print(link)


def _handle_search_api(args) -> None:
    config = _load_config()
    config.ensure_dirs()
    try:
        jobs = search_free_api_jobs(
            args.source,
            query=args.query,
            location=args.location,
            country=args.country,
            board=args.board,
            limit=args.limit,
            page=args.page,
            remote_only=args.remote_only,
            use_cache=args.cache,
            cache_ttl_hours=args.cache_ttl_hours,
        )
    except FreeApiError as exc:
        _fail(f"API search error: {exc}")
    except Exception as exc:
        _fail(f"Failed to search source: {exc}")

    if not jobs:
        console.print("No jobs found.")
        return

    table = Table(title=f"{args.source} results", show_header=True, header_style="bold cyan")
    for col in ["#", "Title", "Company", "Location", "Remote", "Source"]:
        table.add_column(col)
    for idx, job in enumerate(jobs, start=1):
        table.add_row(
            str(idx),
            job.title[:60],
            job.company[:30],
            (job.location or "-")[:30],
            "yes" if job.remote else "no",
            job.apply_url or job.source_url or "-",
        )
    console.print(table)

    if args.save:
        added = 0
        duplicates = 0
        for job in jobs:
            _, created = add_job_to_tracker(config, job)
            if created:
                added += 1
            else:
                duplicates += 1
        console.print(f"Saved {added} new jobs ({duplicates} duplicates skipped).")


def _handle_hunt(args) -> None:
    config = _load_config()
    config.ensure_dirs()
    profile, _, _ = _load_profiles(config)
    if not profile:
        _fail("Cannot hunt without valid profile files. Run job-agent copy-examples and validate-profile first.")
    try:
        jobs = search_free_api_jobs(
            args.source,
            query=args.query,
            location=args.location,
            country=args.country,
            board=args.board,
            limit=args.limit,
            page=args.page,
            remote_only=args.remote_only,
            use_cache=args.cache,
            cache_ttl_hours=args.cache_ttl_hours,
        )
    except FreeApiError as exc:
        _fail(f"API search error: {exc}")
    except Exception as exc:
        _fail(f"Failed to search source: {exc}")

    if not jobs:
        console.print("No jobs found.")
        return

    prepared = 0
    skipped = 0
    failed: list[str] = []
    for job in jobs:
        tracked_job, created = add_job_to_tracker(config, job)
        if not created:
            skipped += 1
            continue
        try:
            generate_packet_for_job(config, tracked_job.id, force=args.force)
            prepared += 1
        except Exception as exc:
            failed.append(f"{tracked_job.title} @ {tracked_job.company}: {exc}")
    console.print(
        Panel(
            f"Imported and prepared packets: {prepared}\nDuplicates skipped: {skipped}\nFailures: {len(failed)}\n\n"
            "Open a packet with: job-agent apply-assist <packet-id>\n"
            "Final application submission is still manual.",
            title="Hunt complete",
        )
    )
    for item in failed[:10]:
        console.print(f"Skipped: {item}")


def _handle_api_sources(args) -> None:
    console.print("Supported sources: " + ", ".join(supported_source_names()))
    console.print("France priority source: francetravail (free credentials required).")
    console.print("All sources are read-only here; final submission remains manual.")


def _handle_france_setup(args) -> None:
    setup_text = (
        "1. Request free France Travail API access for 'API Offres d’emploi'.\n"
        "2. Set these environment variables after approval:\n"
        "   FRANCE_TRAVAIL_CLIENT_ID=...\n"
        "   FRANCE_TRAVAIL_CLIENT_SECRET=...\n"
        "   FRANCE_TRAVAIL_SCOPE='api_offresdemploiv2 o2dsoffre'\n"
        "3. Run: job-agent search-api francetravail --query 'data scientist stage' --location Paris --save\n"
        "4. For Welcome to the Jungle, LinkedIn, Indeed, Glassdoor, HelloWork, Apec, Stage.fr: use france-search-urls, then add promising URLs with job-agent add url.\n\n"
        "This tool does not scrape logged-in boards and does not auto-submit applications."
    )
    console.print(Panel(setup_text, title="France/Paris setup"))


def _handle_france_search_urls(args) -> None:
    queries = [args.query] if args.single_query else expand_france_search_queries(args.query, limit=args.limit)
    notes = board_notes()
    console.print("Boards: " + ", ".join(row[1] for row in build_france_search_urls(args.query, args.location)))
    if not args.single_query:
        console.print("Expanded queries: " + "; ".join(queries))
    table = Table(title=f"France search URLs: {args.query} / {args.location}", show_header=True, header_style="bold cyan")
    for col in ["Query", "Board", "URL", "Note"]:
        table.add_column(col)
    for query in queries:
        for key, name, url in build_france_search_urls(query, args.location):
            table.add_row(query, name, url, notes.get(key, ""))
    console.print(table)


def _handle_france_targets(args) -> None:
    table = Table(title="France CAC 40 / large-company targets", show_header=True, header_style="bold cyan")
    for col in ["Company", "Sector", "Careers URL", "Search hint"]:
        table.add_column(col)
    for target in cac40_targets(limit=args.limit):
        table.add_row(target.name, target.sector, target.careers_url, target.search_hint)
    console.print(table)


def _handle_france_hunt(args) -> None:
    config = _load_config()
    config.ensure_dirs()
    profile, _, _ = _load_profiles(config)
    if not profile and args.packets:
        _fail("Cannot generate packets without valid profile files. Run copy-examples, edit them, then validate-profile.")
    queries = expand_france_search_queries(args.query, limit=args.limit_queries) if args.query.strip() else DEFAULT_FRANCE_DATA_AI_QUERIES[: args.limit_queries]
    imported = duplicates = prepared = 0
    failures: list[str] = []
    for query in queries:
        try:
            jobs = search_free_api_jobs(
                "francetravail",
                query=query,
                location=args.location,
                limit=args.limit,
                use_cache=args.cache,
                cache_ttl_hours=6.0,
            )
        except FreeApiError as exc:
            console.print(f"France Travail not available for query '{query}': {exc}")
            console.print("Run job-agent france-setup, or use job-agent france-search-urls for manual sources.")
            continue
        except Exception as exc:
            failures.append(f"{query}: {exc}")
            continue
        for job in jobs:
            tracked_job, created = add_job_to_tracker(config, job)
            if not created:
                duplicates += 1
                continue
            imported += 1
            if args.packets:
                try:
                    generate_packet_for_job(config, tracked_job.id, force=args.force)
                    prepared += 1
                except Exception as exc:
                    failures.append(f"{tracked_job.title} @ {tracked_job.company}: {exc}")
    console.print(
        Panel(
            f"Imported: {imported}\nDuplicates: {duplicates}\nPackets prepared: {prepared}\nFailures: {len(failures)}\n\n"
            "Manual fallback: job-agent france-search-urls --query 'data science stage' --location Paris",
            title="France hunt complete",
        )
    )
    for item in failures[:10]:
        console.print(f"Skipped: {item}")


def _handle_list(args) -> None:
    config = _load_config()
    tracker = _get_tracker(config)
    status = None
    if args.status:
        try:
            status = JobStatus(args.status.upper())
        except ValueError:
            _fail(f"Unknown status: {args.status}")
    jobs = tracker.list_jobs(status=status)
    if not jobs:
        console.print("No jobs found.")
        return
    table = Table(title="Jobs", show_header=True, header_style="bold cyan")
    for col in ["ID", "Title", "Company", "Status", "Score", "Decision", "Date"]:
        table.add_column(col)
    for job in jobs:
        table.add_row(
            job.id[:8],
            job.title,
            job.company,
            job.status.value,
            str(job.fit_score if job.fit_score is not None else "-"),
            job.fit_decision or "-",
            job.created_at[:10],
        )
    console.print(table)


def _handle_show(args) -> None:
    tracker = _get_tracker(_load_config())
    job = tracker.get_job(args.job_id)
    if not job:
        _fail(f"Job not found: {args.job_id}")
    console.print(
        Panel(
            f"{job.title} @ {job.company}\n"
            f"Status: {job.status.value} | Score: {job.fit_score if job.fit_score is not None else '-'} | Decision: {job.fit_decision or '-'}\n"
            f"Location: {job.location or '-'} | Remote: {job.remote} | Work mode: {job.work_mode or '-'}\n"
            f"Source: {job.source} | Created: {job.created_at[:10]}\n\n"
            f"Description:\n{job.description[:700]}{'...' if len(job.description) > 700 else ''}\n\n"
            f"Tech Stack: {', '.join(job.tech_stack) or '-'}\n"
            f"Apply URL: {job.apply_url or '-'}",
            title=f"Job {job.id[:8]}",
        )
    )


def _handle_score(args) -> None:
    config = _load_config()
    tracker = _get_tracker(config)
    profile, _, _ = _load_profiles(config)
    if not profile:
        _fail("Cannot score without candidate_profile.json.")
    job = tracker.get_job(args.job_id)
    if not job:
        _fail(f"Job not found: {args.job_id}")
    breakdown = score_job(job, profile)
    job.fit_score = breakdown.total_score
    job.fit_confidence = breakdown.confidence
    job.fit_decision = breakdown.decision
    job.fit_notes = breakdown.notes
    job.missing_requirements = breakdown.missing_requirements
    job.risk_flags = sorted(set(job.risk_flags + breakdown.risk_flags))
    tracker.db.save_job(job)
    tracker.update_status(job.id, JobStatus.SCORED)
    console.print(
        Panel(
            f"Total Score: {breakdown.total_score}/100\n"
            f"Decision: {breakdown.decision} | Confidence: {breakdown.confidence:.2f}\n"
            f"Skill: {breakdown.skill_score}/100 | Title: {breakdown.title_score}/100 | Location: {breakdown.location_score}/100\n\n"
            + "\n".join(f"  - {note}" for note in breakdown.notes),
            title=f"Score: {job.title[:40]}",
        )
    )


def _handle_apply(args) -> None:
    config = _load_config()
    config.ensure_dirs()
    try:
        packet = generate_packet_for_job(config, args.job_id, force=args.force)
    except Exception as exc:
        _fail(f"Cannot generate packet: {exc}")
    console.print(
        Panel(
            f"Packet generated\n"
            f"Packet ID: {packet.id}\nStatus: {packet.status.value}\n"
            f"CV PDF: {packet.tailored_cv_pdf_path}\nCover Letter: {packet.cover_letter_pdf_path}\n"
            f"Assistant: {next((a.path for a in packet.artifacts if a.kind == 'assistant_html'), '-')}\n\n"
            "Review everything manually before submitting.",
            title="Application Packet",
        )
    )


def _handle_process_file(args) -> None:
    try:
        job, packet, created = process_file(
            _load_config(),
            args.path,
            title=args.title or None,
            company=args.company or None,
            url=args.url or None,
            force=args.force,
        )
    except Exception as exc:
        _fail(f"Processing failed: {exc}")
    if not created:
        console.print(f"Duplicate detected: existing job {job.id[:8]}")
        return
    assert packet is not None
    console.print(f"Processed {job.title} @ {job.company} | score={packet.fit_score}/100 | packet={packet.id}")


def _handle_status(args) -> None:
    tracker = _get_tracker(_load_config())
    try:
        status = JobStatus(args.new_status.upper())
    except ValueError:
        valid = [status.value for status in JobStatus]
        _fail(f"Unknown status: {args.new_status}. Valid: {valid}")
    try:
        tracker.update_status(args.job_id, status, note=args.note)
    except ValueError as exc:
        _fail(str(exc))
    console.print(f"Updated {args.job_id[:8]} -> {status.value}")


def _handle_history(args) -> None:
    tracker = _get_tracker(_load_config())
    events = tracker.get_history(args.job_id)
    if not events:
        console.print("No events found.")
        return
    table = Table(title=f"History: {args.job_id[:8]}", show_header=True)
    for col in ["#", "Type", "Data", "At"]:
        table.add_column(col)
    for event in events:
        table.add_row(str(event["id"]), event["event_type"], str(event["event_data"]), event["created_at"][:19])
    console.print(table)


def _handle_apply_assist(args) -> None:
    tracker = _get_tracker(_load_config())
    packet = tracker.db.resolve_packet(args.packet_id)
    if not packet:
        _fail(f"Packet not found: {args.packet_id}")
    job = tracker.get_job(packet.job_id)
    packet.status = PacketStatus.ASSISTED_APPLY_OPENED
    tracker.db.save_packet(packet)
    if job:
        job.status = JobStatus.ASSISTED_APPLY_OPENED
        tracker.db.save_job(job)
    tracker.db.log_event(job.id if job else None, "ASSISTED_APPLY_OPENED", {"packet_id": packet.id}, packet_id=packet.id)
    assistant = next((artifact for artifact in packet.artifacts if artifact.kind == "assistant_html"), None)
    if assistant:
        console.print(f"Assistant page: {assistant.path}")
        if args.open_browser:
            webbrowser.open(Path(assistant.path).resolve().as_uri())
    if job and job.apply_url:
        console.print(f"Apply URL: {job.apply_url}")
        if args.open_browser:
            webbrowser.open(job.apply_url)


def _handle_mark_submitted(args) -> None:
    tracker = _get_tracker(_load_config())
    packet = tracker.db.resolve_packet(args.packet_id)
    if not packet:
        _fail(f"Packet not found: {args.packet_id}")
    packet.status = PacketStatus.MANUALLY_SUBMITTED
    tracker.db.save_packet(packet)
    job = tracker.get_job(packet.job_id)
    if job:
        job.status = JobStatus.MANUALLY_SUBMITTED
        tracker.db.save_job(job)
    tracker.db.log_event(packet.job_id, "MANUALLY_SUBMITTED", {"packet_id": packet.id, "note": args.note}, packet_id=packet.id)
    console.print(f"Marked manually submitted: {packet.id}")


def _handle_packet_show(args) -> None:
    tracker = _get_tracker(_load_config())
    packet = tracker.db.resolve_packet(args.job_or_packet_id)
    if packet is None:
        job = tracker.get_job(args.job_or_packet_id)
        if job:
            packets = tracker.db.get_packets_for_job(job.id)
            packet = packets[0] if packets else None
    if not packet:
        console.print("No packet found.")
        return
    artifacts = "\n".join(f"  - {artifact.kind}: {artifact.path}" for artifact in packet.artifacts)
    console.print(
        Panel(
            f"Packet ID: {packet.id}\nVersion: {packet.version}\nStatus: {packet.status.value}\nFit: {packet.fit_score}\n"
            f"CV PDF: {packet.tailored_cv_pdf_path or '-'}\nLetter: {packet.cover_letter_pdf_path or '-'}\nArtifacts:\n{artifacts}",
            title="Packet",
        )
    )


class LocalCLIApp:
    prog = "job-agent"

    def build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=self.prog, description="Free, local-first job-search and application assistant.")
        sub = parser.add_subparsers(dest="command")
        sub.required = True

        init_p = sub.add_parser("init", help="Initialize data directory and config.")
        init_p.set_defaults(handler=_handle_init)

        copy_p = sub.add_parser("copy-examples", help="Copy example profile files.")
        copy_p.set_defaults(handler=_handle_copy_examples)

        validate_p = sub.add_parser("validate-profile", help="Validate candidate profile files.")
        validate_p.set_defaults(handler=_handle_validate_profile)

        add_p = sub.add_parser("add", help="Add jobs from various sources.")
        add_sub = add_p.add_subparsers(dest="add_command")
        add_sub.required = True

        add_paste = add_sub.add_parser("paste", help="Add a job from stdin paste mode.")
        add_paste.add_argument("--title", default="")
        add_paste.add_argument("--company", default="")
        add_paste.add_argument("--url", default="")
        add_paste.set_defaults(handler=_handle_add_paste)

        add_file = add_sub.add_parser("file", help="Add a job from a text/markdown file.")
        add_file.add_argument("path", type=Path)
        add_file.add_argument("--title", default="")
        add_file.add_argument("--company", default="")
        add_file.add_argument("--url", default="")
        add_file.set_defaults(handler=_handle_add_file)

        add_url = add_sub.add_parser("url", help="Add a job from a public URL.")
        add_url.add_argument("url")
        add_url.set_defaults(handler=_handle_add_url)

        add_rss = add_sub.add_parser("rss", help="Add jobs from an RSS/Atom feed.")
        add_rss.add_argument("feed_url")
        add_rss.add_argument("--limit", "-n", type=int, default=None)
        add_rss.set_defaults(handler=_handle_add_rss)

        discover_p = sub.add_parser("discover-links", help="Print likely job/application links.")
        discover_p.add_argument("url")
        discover_p.add_argument("--limit", type=int, default=50)
        discover_p.set_defaults(handler=_handle_discover_links)

        search_p = sub.add_parser("search-api", help="Search free/read-only public job APIs.")
        self._add_search_args(search_p)
        search_p.add_argument("--save", action="store_true")
        search_p.set_defaults(handler=_handle_search_api)

        hunt_p = sub.add_parser("hunt", help="Search, import, score, and prepare local packets.")
        self._add_search_args(hunt_p, default_limit=5)
        hunt_p.add_argument("--force", action="store_true")
        hunt_p.set_defaults(handler=_handle_hunt)

        api_p = sub.add_parser("api-sources", help="List supported free/read-only public job API sources.")
        api_p.set_defaults(handler=_handle_api_sources)

        fs_p = sub.add_parser("france-setup", help="Show France workflow setup instructions.")
        fs_p.set_defaults(handler=_handle_france_setup)

        urls_p = sub.add_parser("france-search-urls", help="Print safe manual search URLs for French job boards.")
        urls_p.add_argument("--query", "-q", default="data science stage")
        urls_p.add_argument("--location", "-l", default="Paris")
        urls_p.add_argument("--single-query", action="store_true", help="Do not expand internship/stage/alternance query variants.")
        urls_p.add_argument("--limit", "-n", type=int, default=18, help="Maximum expanded query variants.")
        urls_p.set_defaults(handler=_handle_france_search_urls)

        targets_p = sub.add_parser("france-targets", help="List CAC 40 / large French company career pages.")
        targets_p.add_argument("--limit", type=int, default=40)
        targets_p.set_defaults(handler=_handle_france_targets)

        fh_p = sub.add_parser("france-hunt", help="France/Paris data-AI hunt using France Travail when configured.")
        fh_p.add_argument("--query", "-q", default="")
        fh_p.add_argument("--location", "-l", default="Paris")
        fh_p.add_argument("--limit", "-n", type=int, default=10)
        fh_p.add_argument("--limit-queries", type=int, default=24)
        fh_p.add_argument("--packets", dest="packets", action="store_true")
        fh_p.add_argument("--no-packets", dest="packets", action="store_false")
        fh_p.set_defaults(packets=True)
        fh_p.add_argument("--cache", dest="cache", action="store_true")
        fh_p.add_argument("--no-cache", dest="cache", action="store_false")
        fh_p.set_defaults(cache=True)
        fh_p.add_argument("--force", action="store_true")
        fh_p.set_defaults(handler=_handle_france_hunt)

        list_p = sub.add_parser("list", help="List tracked jobs.")
        list_p.add_argument("--status", "-s", default="")
        list_p.set_defaults(handler=_handle_list)

        show_p = sub.add_parser("show", help="Show details for a job.")
        show_p.add_argument("job_id")
        show_p.set_defaults(handler=_handle_show)

        score_p = sub.add_parser("score", help="Score a job against your candidate profile.")
        score_p.add_argument("job_id")
        score_p.set_defaults(handler=_handle_score)

        apply_p = sub.add_parser("apply", help="Generate a full local application packet.")
        apply_p.add_argument("job_id")
        apply_p.add_argument("--force", action="store_true")
        apply_p.set_defaults(handler=_handle_apply)

        process_p = sub.add_parser("process", help="One-command job processing.")
        process_sub = process_p.add_subparsers(dest="process_command")
        process_sub.required = True
        process_file_p = process_sub.add_parser("file", help="Process a job description file end to end.")
        process_file_p.add_argument("path", type=Path)
        process_file_p.add_argument("--title", default="")
        process_file_p.add_argument("--company", default="")
        process_file_p.add_argument("--url", default="")
        process_file_p.add_argument("--force", action="store_true")
        process_file_p.set_defaults(handler=_handle_process_file)

        status_p = sub.add_parser("status", help="Update the status of a job.")
        status_p.add_argument("job_id")
        status_p.add_argument("new_status")
        status_p.add_argument("--note", "-n", default="")
        status_p.set_defaults(handler=_handle_status)

        history_p = sub.add_parser("history", help="Show event history for a job.")
        history_p.add_argument("job_id")
        history_p.set_defaults(handler=_handle_history)

        assist_p = sub.add_parser("apply-assist", help="Open the local assistant page and apply URL.")
        assist_p.add_argument("packet_id")
        assist_p.add_argument("--open-browser", dest="open_browser", action="store_true")
        assist_p.add_argument("--no-open-browser", dest="open_browser", action="store_false")
        assist_p.set_defaults(open_browser=True, handler=_handle_apply_assist)

        submitted_p = sub.add_parser("mark-submitted", help="Mark an application packet as manually submitted.")
        submitted_p.add_argument("packet_id")
        submitted_p.add_argument("--note", "-n", default="")
        submitted_p.set_defaults(handler=_handle_mark_submitted)

        packet_p = sub.add_parser("packet", help="Manage application packets.")
        packet_sub = packet_p.add_subparsers(dest="packet_command")
        packet_sub.required = True
        packet_show = packet_sub.add_parser("show", help="Show a packet by job or packet id.")
        packet_show.add_argument("job_or_packet_id")
        packet_show.set_defaults(handler=_handle_packet_show)

        return parser

    def _add_search_args(self, parser: argparse.ArgumentParser, default_limit: int = 10) -> None:
        parser.add_argument("source")
        parser.add_argument("--query", "-q", default="")
        parser.add_argument("--location", "-l", default="")
        parser.add_argument("--country", default="")
        parser.add_argument("--board", default="")
        parser.add_argument("--limit", "-n", type=int, default=default_limit)
        parser.add_argument("--page", type=int, default=1)
        parser.add_argument("--remote-only", action="store_true")
        parser.add_argument("--cache", dest="cache", action="store_true")
        parser.add_argument("--no-cache", dest="cache", action="store_false")
        parser.set_defaults(cache=True)
        parser.add_argument("--cache-ttl-hours", type=float, default=6.0)

    def invoke(self, argv: list[str] | None = None) -> int:
        parser = self.build_parser()
        argv = list(argv or [])
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:
            return int(exc.code or 0)

        handler = getattr(args, "handler", None)
        if handler is None:
            parser.print_help()
            return 1
        try:
            handler(args)
            return 0
        except CLIError as exc:
            console.print(exc.message)
            return exc.code

    def __call__(self) -> None:  # pragma: no cover
        raise SystemExit(self.invoke(sys.argv[1:]))


app = LocalCLIApp()


if __name__ == "__main__":  # pragma: no cover
    app()
