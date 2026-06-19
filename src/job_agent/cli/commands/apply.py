"""Application packet command handlers (apply, process, assist, submit)."""
from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from job_agent.exporters.internship_workbook import export_applied_internships
from job_agent.pipeline import generate_packet_for_job, process_file
from job_agent.schemas.job import JobStatus
from job_agent.schemas.packet import PacketStatus

from job_agent.cli.commands._common import (
    Panel,
    _fail,
    _get_tracker,
    _load_config,
    console,
)


def _handle_apply(args: argparse.Namespace) -> None:
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


def _handle_process_file(args: argparse.Namespace) -> None:
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


def _handle_apply_assist(args: argparse.Namespace) -> None:
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


def _handle_mark_submitted(args: argparse.Namespace) -> None:
    config = _load_config()
    tracker = _get_tracker(config)
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
    try:
        wb_path, count = export_applied_internships(config)
        if count > 0:
            console.print(f"Tracker updated: {count} internship(s) → {wb_path}")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Auto-export tracker failed: %s", exc)


def _handle_packet_show(args: argparse.Namespace) -> None:
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
