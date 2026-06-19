"""Claude-in-Chrome apply bridge.

Reads ready application packets from the local database and generates
step-by-step Chrome automation instructions for Claude to execute.
Claude uses the user's existing logged-in browser session -- no login
automation, no CAPTCHA bypass, no invented facts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, PacketStatus

logger = logging.getLogger(__name__)

_MIN_SCORE_DEFAULT = 65
_PACKET_STATUSES_PENDING = {PacketStatus.READY, PacketStatus.DRAFT, PacketStatus.NEEDS_REVIEW}
# Risk flags that must block auto-apply regardless of score.
_HARD_BLOCK_FLAGS = frozenset({"WORK_AUTH_REQUIRED", "LANGUAGE_MISMATCH"})


@dataclass(frozen=True)
class ApplyCandidate:
    job: JobListing
    packet: ApplicationPacket
    cv_pdf_path: Optional[str]
    cover_letter_md: str
    qa_answers: dict[str, str]


def _get_db() -> Database:
    cfg = AppConfig()
    db = Database(cfg.db_path)  # type: ignore[arg-type]  # db_path is always set by AppConfig
    db.initialize()
    return db


def get_ready_candidates(
    min_score: float = _MIN_SCORE_DEFAULT,
    limit: int = 10,
) -> list[ApplyCandidate]:
    """Return apply-ready packets above the score threshold, newest first."""
    db = _get_db()
    packets = db.list_packets(limit=200)
    candidates: list[ApplyCandidate] = []

    for packet in packets:
        if packet.status not in _PACKET_STATUSES_PENDING:
            continue
        score = packet.fit_score or 0.0
        if score < min_score:
            continue
        hard_blocks = [f for f in (packet.risk_flags or []) if f in _HARD_BLOCK_FLAGS]
        if hard_blocks:
            logger.debug("Skipping %s - hard block flags: %s", packet.id, hard_blocks)
            continue

        job = db.get_job(packet.job_id)
        if not job or not job.apply_url:
            continue
        if job.status in (JobStatus.MANUALLY_SUBMITTED, JobStatus.APPLIED):
            continue

        candidates.append(ApplyCandidate(
            job=job,
            packet=packet,
            cv_pdf_path=packet.tailored_cv_pdf_path,
            cover_letter_md=packet.cover_letter_md,
            qa_answers=packet.qa_answers,
        ))

    candidates.sort(key=lambda c: c.packet.fit_score or 0, reverse=True)
    return candidates[:limit]


def build_chrome_instruction(candidate: ApplyCandidate) -> str:
    """Generate a Claude-in-Chrome instruction block for one application."""
    job = candidate.job
    packet = candidate.packet
    score = packet.fit_score or 0
    decision = packet.fit_decision or "apply"

    cv_path = candidate.cv_pdf_path or "(no PDF -- use tailored CV text below)"
    apply_url = job.apply_url or ""

    # Format QA answers as a readable block
    qa_block = ""
    if candidate.qa_answers:
        lines = [f"  - {q}: {a}" for q, a in candidate.qa_answers.items()]
        qa_block = "\n".join(lines)
    elif packet.screening_answers:
        lines = [
            f"  - {sa['question'] if isinstance(sa, dict) else sa.question}: "
            f"{sa['answer'] if isinstance(sa, dict) else sa.answer}"
            for sa in packet.screening_answers[:20]
        ]
        qa_block = "\n".join(lines)
    else:
        qa_block = "  (no pre-filled answers -- fill from my profile)"

    # Format cover letter (first 400 chars as preview)
    cl_preview = (candidate.cover_letter_md or "").strip()[:400]
    if len(candidate.cover_letter_md) > 400:
        cl_preview += "..."

    instruction = f"""
## Application: {job.title} at {job.company}
**Fit score:** {score:.0f}/100  |  **Decision:** {decision}
**Job ID:** {job.id}  |  **Packet ID:** {packet.id}

### STEP 1 — Navigate to the application
Go to: {apply_url}

Make sure I am already logged in. If not, stop and tell me.

### STEP 2 — Detect the application method
Check whether this is:
- LinkedIn Easy Apply (button says "Easy Apply")
- An external ATS form (Greenhouse, Lever, Ashby, Workday, etc.)
- A direct email application

Report which type you see before proceeding.

### STEP 3 — Fill the form
Use these pre-filled answers for every form field. Do NOT invent or modify any facts:

{qa_block}

For any field not covered above:
- Name, email, phone: use my logged-in profile information
- "Why do you want to work here?" / "Cover letter": paste the cover letter below
- Work authorization / visa sponsorship: use only what is in the answers above; if it is not listed, stop and ask me
- Salary expectation: leave blank unless required; if required, ask me first

### STEP 4 — Upload CV
Upload this file as the CV/resume:
  {cv_path}

If the PDF is not available, tell me and I will provide it manually.

### STEP 5 — Cover letter
If a cover letter field exists, paste this:

{cl_preview}

### STEP 6 — Review before submitting
Show me a summary of all fields you filled before clicking Submit.
Wait for my confirmation before submitting.

### STEP 7 — After submission
After I confirm and you submit:
1. Screenshot or describe the confirmation page
2. Note the application reference number if one appears
3. Report: "Applied to {job.title} at {job.company} -- confirmed"

### SAFETY RULES (enforce strictly)
- Never invent experience, education, metrics, or legal facts
- Never claim sponsorship unless it is explicitly in the QA answers
- Never submit without my final confirmation in Step 6
- If a question requires information not in the QA answers, STOP and ask me
""".strip()

    return instruction


def generate_batch_instructions(
    min_score: float = _MIN_SCORE_DEFAULT,
    limit: int = 10,
    output_path: Optional[Path] = None,
) -> tuple[list[ApplyCandidate], Path]:
    """Generate a Markdown file with Chrome apply instructions for all ready packets.

    Marks each selected job as APPLYING and exports the tracking workbook so
    every session is captured in the Excel tracker immediately.

    Returns the list of candidates and the path to the output file.
    """
    candidates = get_ready_candidates(min_score=min_score, limit=limit)
    cfg = AppConfig()

    if not candidates:
        data_dir = cfg.data_dir
        out = output_path or (data_dir / "chrome_apply_session.md")
        out.write_text(
            "# No ready applications found\n\n"
            f"No packets with fit score >= {min_score} and READY/DRAFT/NEEDS_REVIEW status.\n\n"
            "Run `job-agent france-hunt` or use the Autopilot tab to generate packets first.\n",
            encoding="utf-8",
        )
        return [], out

    # Mark every selected job as APPLYING so the tracker reflects the session.
    db = _get_db()
    for candidate in candidates:
        if candidate.job.status not in (JobStatus.APPLYING, JobStatus.APPLIED, JobStatus.MANUALLY_SUBMITTED):
            db.update_job_status(candidate.job.id, JobStatus.APPLYING)
            db.log_event(
                candidate.job.id,
                "CHROME_SESSION_QUEUED",
                {"packet_id": candidate.packet.id, "fit_score": candidate.packet.fit_score},
                packet_id=candidate.packet.id,
            )
            logger.info("Marked %s as APPLYING", candidate.job.id)

    # Export to Excel immediately so every session is in the tracking file.
    try:
        from job_agent.exporters.internship_workbook import export_applied_internships
        wb_path, count = export_applied_internships(cfg)
        logger.info("Tracking workbook updated: %d row(s) → %s", count, wb_path)
    except Exception as exc:
        logger.warning("Could not update tracking workbook: %s", exc)

    blocks = []
    for i, candidate in enumerate(candidates, 1):
        blocks.append(f"# Application {i} of {len(candidates)}\n\n{build_chrome_instruction(candidate)}")

    header = (
        f"# Claude-in-Chrome Apply Session\n"
        f"Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Applications ready: {len(candidates)} (score >= {min_score})\n\n"
        "---\n\n"
        "**Instructions:** Paste each application block into a Claude conversation "
        "with Chrome access. Claude will navigate to the apply URL, fill the form "
        "using the pre-filled answers, and wait for your confirmation before submitting.\n\n"
        "---\n\n"
    )

    content = header + "\n\n---\n\n".join(blocks)
    data_dir = cfg.data_dir
    out = output_path or (data_dir / "chrome_apply_session.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    logger.info("Wrote %d application instructions to %s", len(candidates), out)
    return candidates, out


def mark_candidate_applying(candidate: ApplyCandidate) -> None:
    """Update job status to APPLYING after Chrome auto-apply session starts."""
    db = _get_db()
    db.update_job_status(candidate.job.id, JobStatus.APPLYING)
    logger.info("Marked job %s as APPLYING", candidate.job.id)
