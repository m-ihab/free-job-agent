"""Job-management command handlers (add, list, show, score, status, enrich)."""
from __future__ import annotations

import argparse
import sys

from job_agent.enrichment import EnrichOptions, enrich_job
from job_agent.intake.file import ingest_file
from job_agent.intake.paste import ingest_paste
from job_agent.intake.url import ingest_url
from job_agent.schemas.job import JobStatus
from job_agent.scorer import score_job

from job_agent.cli.commands._common import (
    Panel,
    Table,
    _add_job,
    _fail,
    _get_tracker,
    _load_config,
    _load_profiles,
    console,
)


def _handle_add_paste(args: argparse.Namespace) -> None:
    console.print("Paste job description below. Press Ctrl+D (Ctrl+Z on Windows) when done:")
    text = sys.stdin.read()
    _add_job(ingest_paste(text, title=args.title or None, company=args.company or None, url=args.url or None), _load_config())


def _handle_add_file(args: argparse.Namespace) -> None:
    _add_job(ingest_file(args.path, title=args.title or None, company=args.company or None, url=args.url or None), _load_config())


def _handle_add_url(args: argparse.Namespace) -> None:
    try:
        job = ingest_url(args.url)
    except Exception as exc:
        _fail(f"Failed to fetch URL: {exc}")
    _add_job(job, _load_config())


def _handle_obsidian_sync(args: argparse.Namespace) -> None:
    """Export the local job DB into a linked Obsidian vault (graph + dashboard)."""
    from job_agent.exporters.obsidian import export_obsidian_vault

    config = _load_config()
    vault_path = getattr(args, "vault", None)
    try:
        vault, count = export_obsidian_vault(config, vault_path=vault_path)
    except Exception as exc:
        _fail(f"Obsidian export failed: {exc}")
    console.print(
        f"Synced {count} job(s) to Obsidian vault: {vault}\n"
        f"Open {vault} in Obsidian and view the graph; start at Dashboard.md."
    )


def _build_enrich_options(args: argparse.Namespace) -> EnrichOptions:
    flags = [
        args.rome,
        args.anotea,
        args.training,
        args.labour_market,
        args.territory,
        args.employer,
        args.other,
    ]
    if not any(flags):
        return EnrichOptions()
    return EnrichOptions(
        rome=args.rome,
        anotea=args.anotea,
        training=args.training,
        labour_market=args.labour_market,
        territory=args.territory,
        employer=args.employer,
        other=args.other,
    )


def _handle_enrich(args: argparse.Namespace) -> None:
    config = _load_config()
    config.ensure_dirs()
    options = _build_enrich_options(args)
    tracker = _get_tracker(config)

    job_ids: list[str] = []
    if args.job_id:
        job_ids = [args.job_id]
    elif args.status:
        try:
            status = JobStatus(args.status.upper())
        except ValueError:
            _fail(f"Unknown status: {args.status}")
        job_ids = [job.id for job in tracker.list_jobs(status=status, limit=args.limit)]
    else:
        _fail("Provide a job id or --status to enrich multiple jobs.")

    if not job_ids:
        console.print("No jobs found for enrichment.")
        return

    for job_id in job_ids:
        report = enrich_job(config, job_id, options)
        sources = report.get("sources", {})
        ok = sum(1 for value in sources.values() if str(value).startswith("ok"))
        console.print(
            Panel(
                f"Job: {job_id}\nEndpoints ok: {ok}/{len(sources)}",
                title="Enrichment complete",
            )
        )


def _handle_list(args: argparse.Namespace) -> None:
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


def _handle_show(args: argparse.Namespace) -> None:
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


def _handle_score(args: argparse.Namespace) -> None:
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


def _handle_status(args: argparse.Namespace) -> None:
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


def _handle_delete_job(args: argparse.Namespace) -> None:
    tracker = _get_tracker(_load_config())
    job = tracker.get_job(args.job_id)
    if not job:
        _fail(f"Job not found: {args.job_id}")
    if not args.yes:
        console.print(f"Refusing to delete without --yes: {job.title} @ {job.company}")
        return
    tracker.delete_job(job.id, note=args.note or "CLI removal")
    console.print(f"Deleted local job: {job.id[:8]} {job.title} @ {job.company}")


def _handle_history(args: argparse.Namespace) -> None:
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
