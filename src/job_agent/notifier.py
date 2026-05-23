"""Local notification helpers for high-fit autopilot discoveries."""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from job_agent.config import AppConfig
from job_agent.schemas.job import JobListing
from job_agent.schemas.packet import ApplicationPacket
from job_agent.timeutil import utc_now


def _configured_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "")
    if not value:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def email_notifier_status() -> dict:
    enabled = _configured_bool("JOB_AGENT_NOTIFY_EMAIL", False)
    smtp_host = os.environ.get("JOB_AGENT_SMTP_HOST", "").strip()
    to_addr = os.environ.get("JOB_AGENT_NOTIFY_TO", "").strip()
    return {
        "enabled": enabled,
        "smtp_configured": bool(smtp_host and to_addr),
        "to": to_addr,
        "smtp_host": smtp_host,
        "local_outbox": True,
    }


def notify_packet_ready(config: AppConfig, job: JobListing, packet: ApplicationPacket, *, reason: str = "Autopilot") -> dict:
    """Write a local email-style notification and optionally send via SMTP."""
    outbox = Path(config.data_dir) / "notifications"
    outbox.mkdir(parents=True, exist_ok=True)
    assistant_path = next((artifact.path for artifact in packet.artifacts if artifact.kind == "assistant_html"), "")
    subject = f"Strong job match: {job.title} at {job.company}"
    body = "\n".join([
        f"{reason} found a high-fit role.",
        "",
        f"Job: {job.title}",
        f"Company: {job.company}",
        f"Location: {job.location or '-'}",
        f"Score: {packet.fit_score if packet.fit_score is not None else job.fit_score}",
        f"Status: {job.status.value}",
        f"Apply URL: {job.apply_url or job.source_url or '-'}",
        "",
        f"CV PDF: {packet.tailored_cv_pdf_path or '-'}",
        f"Cover letter PDF: {packet.cover_letter_pdf_path or '-'}",
        f"Assistant page: {assistant_path or '-'}",
        "",
        "Nothing was submitted automatically. Open the dashboard to review and apply manually.",
    ])

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("JOB_AGENT_NOTIFY_FROM", "job-agent@localhost")
    msg["To"] = os.environ.get("JOB_AGENT_NOTIFY_TO", "")
    msg.set_content(body)

    safe_name = "".join(ch if ch.isalnum() else "-" for ch in f"{job.company}-{job.title}")[:80].strip("-")
    outbox_path = outbox / f"{utc_now().replace(':', '').replace('+', 'Z')}-{safe_name or job.id[:8]}.eml"
    outbox_path.write_text(msg.as_string(), encoding="utf-8")

    sent = False
    error = ""
    status = email_notifier_status()
    if status["enabled"] and status["smtp_configured"]:
        try:
            host = os.environ["JOB_AGENT_SMTP_HOST"]
            port = int(os.environ.get("JOB_AGENT_SMTP_PORT", "587"))
            username = os.environ.get("JOB_AGENT_SMTP_USERNAME", "")
            password = os.environ.get("JOB_AGENT_SMTP_PASSWORD", "")
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.starttls()
                if username:
                    smtp.login(username, password)
                smtp.send_message(msg)
            sent = True
        except Exception as exc:
            error = str(exc)
    return {"outbox_path": str(outbox_path), "sent": sent, "error": error}
