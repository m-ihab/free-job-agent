"""CLI handlers for local thumbs feedback."""

from __future__ import annotations

import argparse

from job_agent.cli.commands._common import Table, _fail, _get_tracker, _load_config, console
from job_agent.feedback import record_feedback


def _handle_feedback(args: argparse.Namespace) -> None:
    tracker = _get_tracker(_load_config())
    if args.list_feedback:
        if args.job_id:
            _fail("Do not provide a job id with --list.")
        records = tracker.db.list_feedback()
        if not records:
            console.print("No job feedback found.")
            return
        table = Table(title="Job feedback", show_header=True)
        for column in ["ID", "Verdict", "Company", "Title keywords", "Source", "Rated"]:
            table.add_column(column)
        for record in records:
            table.add_row(
                record.job_id[:8],
                record.verdict,
                record.company,
                ", ".join(record.title_keywords),
                record.source,
                record.created_at[:19],
            )
        console.print(table)
        return

    if not args.job_id:
        _fail("A job id is required unless --list is used.")
    verdict = "up" if args.up else "down"
    try:
        saved = record_feedback(tracker.db, args.job_id, verdict)
    except ValueError as exc:
        _fail(str(exc))
    console.print(f"Recorded thumbs {saved.verdict} for {saved.job_id[:8]} ({saved.company}).")
