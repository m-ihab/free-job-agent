"""Typer CLI for free-job-agent."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.fingerprint import set_fingerprint
from job_agent.normalizer import normalize
from job_agent.schemas.job import JobStatus
from job_agent.schemas.packet import PacketStatus
from job_agent.tracker import ApplicationTracker

app = typer.Typer(
    name="job-agent",
    help="Free, local-first job-search and application assistant.",
    no_args_is_help=True,
)
add_app = typer.Typer(help="Add jobs from various sources.", no_args_is_help=True)
packet_app = typer.Typer(help="Manage application packets.", no_args_is_help=True)
app.add_typer(add_app, name="add")
app.add_typer(packet_app, name="packet")

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config() -> AppConfig:
    return AppConfig.load()


def _get_tracker(config: AppConfig) -> ApplicationTracker:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    return ApplicationTracker(db)


def _load_profiles(config: AppConfig) -> tuple:
    """Load candidate_profile, master_cv, qa_profile.  Returns (profile, cv, qa)."""
    from job_agent.schemas.candidate import CandidateProfile, MasterCV, QAProfile

    profiles_dir = config.profiles_dir or (config.data_dir / "profiles")
    profile, master_cv, qa_profile = None, None, None

    cp_path = profiles_dir / "candidate_profile.json"
    if cp_path.exists():
        with open(cp_path) as f:
            profile = CandidateProfile(**json.load(f))
    else:
        console.print(
            f"[yellow]Warning:[/yellow] candidate_profile.json not found at {cp_path}. "
            "Scoring/generation will be limited."
        )

    cv_path = profiles_dir / "master_cv.json"
    if cv_path.exists():
        with open(cv_path) as f:
            master_cv = MasterCV(**json.load(f))
    else:
        console.print(f"[yellow]Warning:[/yellow] master_cv.json not found at {cv_path}.")

    qa_path = profiles_dir / "master_qa_profile.json"
    if qa_path.exists():
        with open(qa_path) as f:
            qa_profile = QAProfile(**json.load(f))
    else:
        console.print(f"[yellow]Warning:[/yellow] master_qa_profile.json not found at {qa_path}.")

    return profile, master_cv, qa_profile


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def init() -> None:
    """Initialize data directory and config."""
    config = AppConfig()
    config.ensure_dirs()
    config.save()
    console.print(f"[green]Initialized[/green] job-agent data directory at: {config.data_dir}")
    console.print(
        f"Place your profile files in: {config.profiles_dir}\n"
        "  - candidate_profile.json\n"
        "  - master_cv.json\n"
        "  - master_qa_profile.json"
    )


@add_app.command("paste")
def add_paste() -> None:
    """Add a job from stdin (paste mode)."""
    from job_agent.intake.paste import ingest_paste

    console.print("[bold]Paste job description below. Press Ctrl+D (or Ctrl+Z on Windows) when done:[/bold]")
    try:
        text = sys.stdin.read()
    except KeyboardInterrupt:
        raise typer.Exit()

    config = _load_config()
    tracker = _get_tracker(config)

    job = ingest_paste(text)
    job = normalize(job)
    job = set_fingerprint(job)

    existing = tracker.db.get_job_by_fingerprint(job.fingerprint)
    if existing:
        console.print(f"[yellow]Duplicate detected.[/yellow] Job already exists: {existing.id}")
        return

    tracker.add_job(job)
    console.print(f"[green]Added job[/green] {job.id[:8]} — {job.title} @ {job.company}")


@add_app.command("file")
def add_file(path: Path = typer.Argument(..., help="Path to job description file")) -> None:
    """Add a job from a text/markdown file."""
    from job_agent.intake.file import ingest_file

    if not path.exists():
        console.print(f"[red]File not found:[/red] {path}")
        raise typer.Exit(1)

    config = _load_config()
    tracker = _get_tracker(config)

    job = ingest_file(path)
    job = normalize(job)
    job = set_fingerprint(job)

    existing = tracker.db.get_job_by_fingerprint(job.fingerprint)
    if existing:
        console.print(f"[yellow]Duplicate detected.[/yellow] Job already exists: {existing.id}")
        return

    tracker.add_job(job)
    console.print(f"[green]Added job[/green] {job.id[:8]} — {job.title} @ {job.company}")


@add_app.command("url")
def add_url(url: str = typer.Argument(..., help="URL of job posting")) -> None:
    """Add a job from a public URL."""
    from job_agent.intake.url import ingest_url

    config = _load_config()
    tracker = _get_tracker(config)

    try:
        job = ingest_url(url)
    except Exception as e:
        console.print(f"[red]Failed to fetch URL:[/red] {e}")
        raise typer.Exit(1)

    job = normalize(job)
    job = set_fingerprint(job)

    existing = tracker.db.get_job_by_fingerprint(job.fingerprint)
    if existing:
        console.print(f"[yellow]Duplicate detected.[/yellow] Job already exists: {existing.id}")
        return

    tracker.add_job(job)
    console.print(f"[green]Added job[/green] {job.id[:8]} — {job.title} @ {job.company}")


@add_app.command("rss")
def add_rss(
    feed_url: str = typer.Argument(..., help="RSS/Atom feed URL"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Max entries to import"),
) -> None:
    """Add jobs from an RSS/Atom feed."""
    from job_agent.intake.rss import ingest_rss

    config = _load_config()
    tracker = _get_tracker(config)

    jobs = ingest_rss(feed_url, limit=limit)
    added = 0
    for job in jobs:
        job = normalize(job)
        job = set_fingerprint(job)
        existing = tracker.db.get_job_by_fingerprint(job.fingerprint)
        if existing:
            continue
        tracker.add_job(job)
        added += 1

    console.print(f"[green]Imported {added}/{len(jobs)} new jobs[/green] from RSS feed.")


@app.command("list")
def list_jobs(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
) -> None:
    """List tracked jobs."""
    config = _load_config()
    tracker = _get_tracker(config)

    js = None
    if status:
        try:
            js = JobStatus(status.upper())
        except ValueError:
            console.print(f"[red]Unknown status:[/red] {status}")
            raise typer.Exit(1)

    jobs = tracker.list_jobs(status=js)

    if not jobs:
        console.print("[dim]No jobs found.[/dim]")
        return

    table = Table(title="Jobs", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=10)
    table.add_column("Title", min_width=25)
    table.add_column("Company", min_width=15)
    table.add_column("Status", min_width=12)
    table.add_column("Score", justify="right", width=7)
    table.add_column("Date", width=12)

    for job in jobs:
        score_str = f"{job.fit_score:.2f}" if job.fit_score is not None else "—"
        date_str = job.created_at[:10]
        table.add_row(
            job.id[:8],
            job.title,
            job.company,
            job.status.value,
            score_str,
            date_str,
        )

    console.print(table)


@app.command()
def show(job_id: str = typer.Argument(..., help="Job ID (or prefix)")) -> None:
    """Show details for a job."""
    config = _load_config()
    tracker = _get_tracker(config)

    job = tracker.get_job(job_id)
    if not job:
        # Try prefix match
        all_jobs = tracker.list_jobs()
        matches = [j for j in all_jobs if j.id.startswith(job_id)]
        if len(matches) == 1:
            job = matches[0]
        elif len(matches) > 1:
            console.print(f"[yellow]Ambiguous prefix:[/yellow] {len(matches)} jobs match.")
            return
        else:
            console.print(f"[red]Job not found:[/red] {job_id}")
            raise typer.Exit(1)

    console.print(Panel(
        f"[bold]{job.title}[/bold] @ {job.company}\n"
        f"Status: {job.status.value}  |  Score: {job.fit_score or '—'}\n"
        f"Location: {job.location or '—'}  |  Remote: {job.remote}\n"
        f"Source: {job.source}  |  Created: {job.created_at[:10]}\n\n"
        f"[bold]Description:[/bold]\n{job.description[:500]}{'...' if len(job.description) > 500 else ''}\n\n"
        f"[bold]Tech Stack:[/bold] {', '.join(job.tech_stack) or '—'}\n"
        f"[bold]Apply URL:[/bold] {job.apply_url or '—'}",
        title=f"Job {job.id[:8]}",
    ))


@app.command()
def score(job_id: str = typer.Argument(..., help="Job ID")) -> None:
    """Score a job against your candidate profile."""
    from job_agent.scorer import score_job

    config = _load_config()
    tracker = _get_tracker(config)
    profile, _, _ = _load_profiles(config)

    if not profile:
        console.print("[red]Cannot score without a candidate profile.[/red]")
        raise typer.Exit(1)

    job = tracker.get_job(job_id)
    if not job:
        console.print(f"[red]Job not found:[/red] {job_id}")
        raise typer.Exit(1)

    breakdown = score_job(job, profile)
    job.fit_score = breakdown.total_score
    job.fit_notes = breakdown.notes
    tracker.db.save_job(job)
    tracker.update_status(job_id, JobStatus.SCORED)

    console.print(Panel(
        f"[bold]Total Score:[/bold] {breakdown.total_score:.2f}\n"
        f"  Skill:    {breakdown.skill_score:.2f}\n"
        f"  Title:    {breakdown.title_score:.2f}\n"
        f"  Location: {breakdown.location_score:.2f}\n\n"
        + "\n".join(f"  • {n}" for n in breakdown.notes),
        title=f"Score: {job.title[:40]}",
    ))


@app.command()
def apply(job_id: str = typer.Argument(..., help="Job ID")) -> None:
    """Generate a full application packet for a job."""
    from job_agent.filters import FilterConfig, apply_filters
    from job_agent.generator.cover_letter import generate_cover_letter
    from job_agent.generator.cv import tailor_cv
    from job_agent.generator.qa import answer_screening_questions
    from job_agent.renderer.html_render import render_html
    from job_agent.renderer.pdf_render import render_pdf
    from job_agent.schemas.packet import ApplicationPacket
    from job_agent.scorer import score_job
    import datetime

    config = _load_config()
    config.ensure_dirs()
    tracker = _get_tracker(config)
    profile, master_cv, qa_profile = _load_profiles(config)

    job = tracker.get_job(job_id)
    if not job:
        console.print(f"[red]Job not found:[/red] {job_id}")
        raise typer.Exit(1)

    # Normalize + fingerprint
    job = normalize(job)
    job = set_fingerprint(job)

    # Filter check
    filter_cfg = FilterConfig()
    if profile:
        filter_result = apply_filters(job, filter_cfg, profile)
        if not filter_result.passed:
            console.print("[yellow]Warning:[/yellow] Job failed filters:")
            for r in filter_result.reasons:
                console.print(f"  • {r}")

    # Score
    if profile:
        breakdown = score_job(job, profile)
        job.fit_score = breakdown.total_score
        job.fit_notes = breakdown.notes
    tracker.db.save_job(job)

    if not master_cv:
        console.print("[red]Cannot generate packet without master_cv.json[/red]")
        raise typer.Exit(1)
    if not profile:
        console.print("[red]Cannot generate packet without candidate_profile.json[/red]")
        raise typer.Exit(1)

    # Generate content
    cv_md = tailor_cv(job, master_cv, profile)
    letter_md = generate_cover_letter(job, master_cv, profile)

    qa_answers: dict[str, str] = {}
    if qa_profile:
        qa_answers = answer_screening_questions([], qa_profile, profile)

    cv_html = render_html(cv_md, title=f"CV — {job.title}")
    letter_html = render_html(letter_md, title=f"Cover Letter — {job.title}")

    # Write files
    out_dir = config.outputs_dir / job.id[:8]  # type: ignore[operator]
    out_dir.mkdir(parents=True, exist_ok=True)

    cv_pdf_path = render_pdf(cv_md, out_dir / "cv.pdf", title="Tailored CV")
    letter_pdf_path = render_pdf(letter_md, out_dir / "cover_letter.pdf", title="Cover Letter")

    # Build assistant page
    assistant_html = render_html(
        f"# Application Assistant\n\n"
        f"**Job:** {job.title} @ {job.company}\n\n"
        f"**Score:** {job.fit_score or '—'}\n\n"
        f"**CV PDF:** {cv_pdf_path}\n\n"
        f"**Cover Letter PDF:** {letter_pdf_path}\n\n"
        f"**Apply URL:** {job.apply_url or 'N/A'}\n",
        title="Application Assistant",
    )
    assistant_path = out_dir / "assistant.html"
    assistant_path.write_text(assistant_html, encoding="utf-8")

    packet = ApplicationPacket(
        job_id=job.id,
        tailored_cv_md=cv_md,
        tailored_cv_html=cv_html,
        tailored_cv_pdf_path=str(cv_pdf_path),
        cover_letter_md=letter_md,
        cover_letter_html=letter_html,
        cover_letter_pdf_path=str(letter_pdf_path),
        qa_answers=qa_answers,
        assistant_page_html=assistant_html,
        status=PacketStatus.READY,
    )
    tracker.save_packet(packet)
    tracker.update_status(job.id, JobStatus.PACKET_READY)

    console.print(Panel(
        f"[green]Packet generated![/green]\n"
        f"  CV PDF:          {cv_pdf_path}\n"
        f"  Cover Letter:    {letter_pdf_path}\n"
        f"  Assistant page:  {assistant_path}\n\n"
        f"[bold yellow]⚠  Review all documents before submitting.[/bold yellow]\n"
        f"[bold yellow]   This tool NEVER auto-submits applications.[/bold yellow]",
        title=f"Packet for {job.title[:40]}",
    ))


@app.command()
def status(
    job_id: str = typer.Argument(..., help="Job ID"),
    new_status: str = typer.Argument(..., help="New status"),
    note: str = typer.Option("", "--note", "-n", help="Optional note"),
) -> None:
    """Update the status of a job."""
    config = _load_config()
    tracker = _get_tracker(config)

    try:
        js = JobStatus(new_status.upper())
    except ValueError:
        valid = [s.value for s in JobStatus]
        console.print(f"[red]Unknown status:[/red] {new_status}. Valid: {valid}")
        raise typer.Exit(1)

    tracker.update_status(job_id, js, note=note)
    console.print(f"[green]Updated[/green] {job_id[:8]} → {js.value}")


@app.command()
def history(job_id: str = typer.Argument(..., help="Job ID")) -> None:
    """Show event history for a job."""
    config = _load_config()
    tracker = _get_tracker(config)

    events = tracker.get_history(job_id)
    if not events:
        console.print("[dim]No events found.[/dim]")
        return

    table = Table(title=f"History: {job_id[:8]}", show_header=True)
    table.add_column("#", width=4)
    table.add_column("Type", min_width=20)
    table.add_column("Data")
    table.add_column("At", width=22)

    for ev in events:
        table.add_row(
            str(ev["id"]),
            ev["event_type"],
            str(ev["event_data"]),
            ev["created_at"][:19],
        )

    console.print(table)


@packet_app.command("show")
def packet_show(job_id: str = typer.Argument(..., help="Job ID")) -> None:
    """Show the latest application packet for a job."""
    config = _load_config()
    tracker = _get_tracker(config)

    packets = tracker.db.get_packets_for_job(job_id)
    if not packets:
        console.print("[dim]No packets found for this job.[/dim]")
        return

    p = packets[0]
    console.print(Panel(
        f"Packet ID: {p.id}\n"
        f"Version:   {p.version}\n"
        f"Status:    {p.status.value}\n"
        f"CV PDF:    {p.tailored_cv_pdf_path or '—'}\n"
        f"Letter:    {p.cover_letter_pdf_path or '—'}\n"
        f"Created:   {p.created_at[:19]}",
        title=f"Packet for job {job_id[:8]}",
    ))
