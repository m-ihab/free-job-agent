"""Career Engine CLI handlers."""
from __future__ import annotations

import argparse

from job_agent.career import build_gap_report, write_gap_report
from job_agent.career.cert_track import build_cert_plan, write_cert_plan
from job_agent.career.project_audit import build_project_audit, write_project_audit
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


def _handle_cert_plan(args: argparse.Namespace) -> None:
    if not 0 <= args.threshold <= 100:
        _fail("--threshold must be between 0 and 100.")
    if not 3 <= args.top <= 5:
        _fail("--top must be between 3 and 5.")
    config = _load_config()
    tracker = _get_tracker(config)
    profile, master_cv, qa_profile = _load_profiles(config)
    if profile is None or master_cv is None or qa_profile is None:
        _fail("Cannot build a certification plan without the complete local profile bundle.")
    evidence = EvidenceStore(tracker.db, build_evidence_items(profile, master_cv, qa_profile))
    gaps = build_gap_report(tracker.db, profile, evidence, threshold=args.threshold)
    plan = build_cert_plan(gaps.clusters, top=args.top)
    if args.json_path is not None:
        write_cert_plan(plan, args.json_path)
    table = Table(title=f"Certification plan: {len(plan.recommendations)} targeted credential(s)")
    for column in ["Rank", "Certification", "Issuer", "Gap coverage", "Signal/hour", "Roles moved"]:
        table.add_column(column)
    for rank, recommendation in enumerate(plan.recommendations, start=1):
        cert = recommendation.certification
        table.add_row(
            str(rank),
            cert.name,
            cert.issuer,
            ", ".join(recommendation.matched_gaps),
            f"{recommendation.signal_per_hour:.4f}",
            ", ".join(cert.roles_it_moves),
        )
    console.print(table)
    if not plan.recommendations:
        console.print("No catalog certifications matched the current gap clusters.")
    for warning in plan.warnings:
        console.print(f"Warning: {warning}")
    if args.json_path is not None:
        console.print(f"JSON: {args.json_path}")


def _handle_project_plan(args: argparse.Namespace) -> None:
    if not 0 <= args.threshold <= 100:
        _fail("--threshold must be between 0 and 100.")
    if not 4 <= args.top <= 6:
        _fail("--top must be between 4 and 6.")
    config = _load_config()
    tracker = _get_tracker(config)
    profile, master_cv, qa_profile = _load_profiles(config)
    if profile is None or master_cv is None or qa_profile is None:
        _fail("Cannot audit projects without the complete local profile bundle.")
    evidence = EvidenceStore(tracker.db, build_evidence_items(profile, master_cv, qa_profile))
    gaps = build_gap_report(tracker.db, profile, evidence, threshold=args.threshold)
    report = build_project_audit(profile, master_cv, evidence, gaps.clusters, top=args.top)
    if args.json_path is not None:
        write_project_audit(report, args.json_path)
    audit_table = Table(title=f"Project audit: {len(report.project_verdicts)} existing project(s)")
    for column in ["Project", "Verdict", "Metrics", "Target stack", "Why"]:
        audit_table.add_column(column)
    for verdict in report.project_verdicts:
        audit_table.add_row(
            verdict.name,
            verdict.verdict,
            "yes" if verdict.has_metrics else "no",
            ", ".join(verdict.matched_target_stack) or "none",
            "; ".join(verdict.reasons),
        )
    console.print(audit_table)
    plan_table = Table(title=f"Project masterplan: top {len(report.masterplan)}")
    for column in ["Rank", "Project", "Covered gaps", "Visibility", "Hours", "Hard part"]:
        plan_table.add_column(column)
    for rank, spec in enumerate(report.masterplan, start=1):
        plan_table.add_row(
            str(rank),
            spec.name,
            ", ".join(spec.covered_gaps) or "role-strengthening",
            str(spec.recruiter_visibility),
            str(spec.time_budget_h),
            spec.hard_part,
        )
    console.print(plan_table)
    if args.json_path is not None:
        console.print(f"JSON: {args.json_path}")
