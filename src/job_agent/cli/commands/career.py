"""Career Engine CLI handlers."""
from __future__ import annotations

import argparse

from job_agent.career import build_gap_report, write_gap_report
from job_agent.evidence import EvidenceStore, build_evidence_items

from job_agent.cli.commands._common import Table, _fail, _get_tracker, _load_config, _load_profiles, console


def _handle_gap_report(args: argparse.Namespace) -> None:
    if not 0 <= args.threshold <= 100:
        _fail("--threshold must be between 0 and 100.")
    if args.top < 1:
        _fail("--top must be at least 1.")
    config = _load_config()
    tracker = _get_tracker(config)
    profile, master_cv, qa_profile = _load_profiles(config)
    if profile is None or master_cv is None or qa_profile is None:
        _fail("Cannot build a gap report without the complete local profile bundle.")
    evidence = EvidenceStore(tracker.db, build_evidence_items(profile, master_cv, qa_profile))
    report = build_gap_report(
        tracker.db,
        profile,
        evidence,
        threshold=args.threshold,
        top=args.top,
    )
    if args.json_path is not None:
        write_gap_report(report, args.json_path)
    if not report.clusters:
        console.print(
            f"Gap report: no scored jobs below {report.threshold} "
            f"({report.scored_job_count} scored job(s) checked)."
        )
        if args.json_path is not None:
            console.print(f"JSON: {args.json_path}")
        return
    table = Table(title=f"Gap report: {report.low_score_job_count}/{report.scored_job_count} scored jobs below {report.threshold}")
    for column in ["Rank", "Gap cluster", "Jobs", "Market share", "Impact pts", "Simulated lift"]:
        table.add_column(column)
    for rank, cluster in enumerate(report.clusters, start=1):
        job_count = len({row.job_id for row in cluster.evidence})
        impact = sum(row.score_impact for row in cluster.evidence)
        table.add_row(
            str(rank),
            cluster.name,
            str(job_count),
            f"{cluster.market_share_pct:.2f}%",
            f"{impact:.2f}",
            f"+{cluster.simulated_score_lift.average_points:.2f} simulated",
        )
    console.print(table)
    receipts = ", ".join(
        f"{cluster.name}={len({row.job_id for row in cluster.evidence})} job(s)"
        for cluster in report.clusters
    )
    console.print(f"Receipts: {receipts}")
    if args.json_path is not None:
        console.print(f"JSON: {args.json_path}")
