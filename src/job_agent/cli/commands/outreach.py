"""Outreach, coaching, and market-intelligence command handlers."""
from __future__ import annotations

import argparse
from pathlib import Path

from job_agent.generator.followup_email import generate_followup_email
from job_agent.generator.interview_prep import generate_interview_prep
from job_agent.generator.linkedin_message import (
    generate_linkedin_connect_request,
    generate_linkedin_followup_message,
    generate_linkedin_recruiter_message,
)
from job_agent.generator.outreach_email import generate_outreach_email
from job_agent.headhunter import (
    build_batch_outreach,
    english_first_strategy_report,
    write_batch_outreach_file,
)
from job_agent.market_intelligence import build_market_report
from job_agent.validators import load_profile_bundle

from job_agent.cli.commands._common import (
    Panel,
    _fail,
    _get_tracker,
    _load_config,
    console,
)


def _handle_outreach(args: argparse.Namespace) -> None:
    """Print a recruiter outreach email draft for a job to stdout."""
    config = _load_config()
    tracker = _get_tracker(config)
    job = tracker.db.resolve_job(args.job_id)
    if not job:
        _fail(f"Job not found: {args.job_id}")
    profile, master_cv, _ = load_profile_bundle(config)
    email_md = generate_outreach_email(job, master_cv, profile)
    console.print(email_md)
    if job.recruiter_name:
        console.print(f"\n[dim]Recruiter: {job.recruiter_name}[/dim]")
    if job.recruiter_email:
        console.print(f"[dim]Email: {job.recruiter_email}[/dim]")


def _handle_linkedin_message(args: argparse.Namespace) -> None:
    """Print a LinkedIn message for a job to stdout."""
    config = _load_config()
    tracker = _get_tracker(config)
    job = tracker.db.resolve_job(args.job_id)
    if not job:
        _fail(f"Job not found: {args.job_id}")
    profile, master_cv, _ = load_profile_bundle(config)
    msg_type = args.type or "recruiter"
    if msg_type == "connect":
        msg = generate_linkedin_connect_request(job, master_cv, profile)
    elif msg_type == "followup":
        msg = generate_linkedin_followup_message(job, master_cv, profile)
    else:
        msg = generate_linkedin_recruiter_message(job, master_cv, profile)
    console.print(msg)
    if job.recruiter_name:
        console.print(f"\n[dim]Recruiter: {job.recruiter_name}[/dim]")


def _handle_market_report(args: argparse.Namespace) -> None:
    """Print a job market intelligence report from tracked jobs."""
    config = _load_config()
    tracker = _get_tracker(config)
    profile, _, _ = load_profile_bundle(config)
    tracked_jobs = tracker.list_jobs(limit=None)
    report = build_market_report(tracked_jobs, set(profile.all_skill_names()))
    md = report.to_markdown()
    console.print(md)
    if args.output:
        args.output.write_text(md, encoding="utf-8")
        console.print(f"[dim]Saved to {args.output}[/dim]")


def _handle_interview_prep(args: argparse.Namespace) -> None:
    """Generate interview prep sheet for a job."""
    config = _load_config()
    tracker = _get_tracker(config)
    job = tracker.db.resolve_job(args.job_id)
    if not job:
        _fail(f"Job not found: {args.job_id}")
    profile, master_cv, _ = load_profile_bundle(config)
    prep = generate_interview_prep(job, master_cv, profile)
    console.print(prep)
    if args.save:
        packets = tracker.db.get_packets_for_job(job.id)
        if packets:
            out_dir = Path(packets[-1].tailored_cv_pdf_path).parent if packets[-1].tailored_cv_pdf_path else None
            if out_dir and out_dir.exists():
                path = out_dir / "interview_prep.md"
                path.write_text(prep, encoding="utf-8")
                console.print(f"[dim]Saved to {path}[/dim]")


def _handle_followup_email(args: argparse.Namespace) -> None:
    """Generate a follow-up email for an applied job."""
    config = _load_config()
    tracker = _get_tracker(config)
    job = tracker.db.resolve_job(args.job_id)
    if not job:
        _fail(f"Job not found: {args.job_id}")
    profile, master_cv, _ = load_profile_bundle(config)
    email = generate_followup_email(job, master_cv, profile, follow_type=args.type or "week1")
    console.print(email)


def _handle_headhunter_batch(args: argparse.Namespace) -> None:
    """Generate a ready-to-send outreach pack for all high-scoring saved jobs."""
    config = _load_config()
    tracker = _get_tracker(config)
    profile, master_cv, _ = load_profile_bundle(config)
    jobs = tracker.list_jobs(limit=None)
    packs = build_batch_outreach(
        jobs,
        master_cv,
        profile,
        min_score=args.min_score,
        english_first_only=args.english_first,
    )
    if not packs:
        console.print(f"No jobs found with score ≥ {args.min_score}. Run scoring first with: job-agent score <job-id>")
        return
    out = args.output or (Path(config.outputs_dir) / "batch_outreach.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    count = write_batch_outreach_file(packs, out)
    console.print(Panel(
        f"Generated {count} outreach packs\n"
        f"Saved to: {out}\n\n"
        "Review every message manually before sending. Never auto-send.",
        title="Headhunter batch complete",
    ))


def _handle_headhunter_strategy(args: argparse.Namespace) -> None:
    """Show which tracked jobs are at English-first companies."""
    config = _load_config()
    tracker = _get_tracker(config)
    jobs = tracker.list_jobs(limit=None)
    report = english_first_strategy_report(jobs)
    console.print(report)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        console.print(f"[dim]Saved to {args.output}[/dim]")
