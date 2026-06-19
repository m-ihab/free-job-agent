"""Export applied internship applications to an Excel workbook."""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.intake.internships import is_internship_listing
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.tracker import ApplicationTracker


# Generic, repo-safe default name. The actual filename used is configurable
# via JOB_AGENT_INTERNSHIP_WORKBOOK so users can keep their private tracker
# under any name they like. Legacy custom files in profiles/ are still
# detected automatically.
DEFAULT_WORKBOOK_NAME = "internship_tracker.xlsx"
LEGACY_WORKBOOK_CANDIDATES = (
    # Names some users had from earlier versions of the project. We still
    # write to them if they exist so no historical data gets orphaned.
    "Internship Search Tracking File A24.xlsx",
    "Internship Tracking.xlsx",
)
EXPORT_COLUMNS = [
    "company name",
    "job title",
    "link to job",
    "job description",
    "location",
    "status",
    "company contact details",
    "date applied",
]
APPLIED_STATUSES = {JobStatus.APPLYING, JobStatus.APPLIED, JobStatus.MANUALLY_SUBMITTED}
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")


def _normalise(text: object) -> str:
    return str(text or "").strip().casefold()


def _default_workbook_path(config: AppConfig, workbook_path: Path | str | None) -> Path:
    """Resolve the destination workbook path.

    Precedence:
    1. Explicit ``workbook_path`` from the caller.
    2. ``JOB_AGENT_INTERNSHIP_WORKBOOK`` env var.
    3. A legacy file in ``profiles/`` if one already exists (don't orphan
       prior user data).
    4. Generic default ``internship_tracker.xlsx``.
    """
    if workbook_path is not None:
        return Path(workbook_path).expanduser()
    env_override = (os.environ.get("JOB_AGENT_INTERNSHIP_WORKBOOK") or "").strip()
    if env_override:
        return Path(env_override).expanduser()
    assert config.profiles_dir is not None
    profiles_dir = Path(config.profiles_dir)
    for legacy in LEGACY_WORKBOOK_CANDIDATES:
        candidate = profiles_dir / legacy
        if candidate.exists():
            return candidate
    return profiles_dir / DEFAULT_WORKBOOK_NAME


def _sheet_and_header_row(worksheet) -> tuple[int, dict[str, int]]:
    expected = {_normalise(column) for column in EXPORT_COLUMNS}
    for row_index in range(1, min(worksheet.max_row, 20) + 1):
        header_map: dict[str, int] = {}
        for cell in worksheet[row_index]:
            label = _normalise(cell.value)
            if label in expected and label not in header_map:
                header_map[label] = cell.column
        if len(header_map) >= 4:
            return row_index, header_map

    for column_index, column_name in enumerate(EXPORT_COLUMNS, start=1):
        worksheet.cell(row=1, column=column_index, value=column_name.title())
    return 1, {name: index for index, name in enumerate(EXPORT_COLUMNS, start=1)}


def _ensure_headers(worksheet, header_row: int, header_map: dict[str, int]) -> dict[str, int]:
    for column_name in EXPORT_COLUMNS:
        key = _normalise(column_name)
        if key not in header_map:
            header_map[key] = len(header_map) + 1
            worksheet.cell(row=header_row, column=header_map[key], value=column_name.title())
    return header_map


def _applied_at(tracker: ApplicationTracker, job: JobListing) -> str:
    expected_statuses = {_normalise(status.value) for status in APPLIED_STATUSES}
    for event in tracker.get_history(job.id):
        event_type = _normalise(event.get("event_type"))
        event_data = event.get("event_data") or {}
        new_status = _normalise(event_data.get("new_status"))
        if event_type in ("manually_submitted", "chrome_session_queued") or new_status in expected_statuses:
            return str(event.get("created_at") or job.updated_at or job.created_at)[:10]
    return str(job.updated_at or job.created_at)[:10]


def _contact_details(job: JobListing) -> str:
    parts: list[str] = []
    text = "\n".join([job.description or "", job.raw_text or ""])
    emails = list(dict.fromkeys(_EMAIL_RE.findall(text)))
    phones = list(dict.fromkeys(_PHONE_RE.findall(text)))
    if emails:
        parts.append("Emails: " + "; ".join(emails[:3]))
    if phones:
        parts.append("Phones: " + "; ".join(phones[:2]))
    if parts:
        return " | ".join(parts)
    for candidate in (job.apply_url, job.source_url):
        if not candidate:
            continue
        parsed = urlparse(candidate)
        if parsed.hostname:
            return f"Portal: {parsed.hostname}"
        return candidate
    return ""


def _status_label(job: JobListing) -> str:
    if job.status in {JobStatus.APPLIED, JobStatus.MANUALLY_SUBMITTED}:
        return "Applied"
    if job.status == JobStatus.APPLYING:
        return "Applying"
    return job.status.value.replace("_", " ").title()


def export_applied_internships(
    config: AppConfig,
    *,
    workbook_path: Path | str | None = None,
    sheet_name: str | None = None,
) -> tuple[Path, int]:
    """Write submitted internship applications into the tracking workbook."""
    config.ensure_dirs()
    # ensure_dirs() guarantees db_path is set
    tracker = ApplicationTracker(Database(config.db_path))  # type: ignore[arg-type]
    workbook_file = _default_workbook_path(config, workbook_path)
    workbook_file.parent.mkdir(parents=True, exist_ok=True)

    if workbook_file.exists():
        workbook = load_workbook(workbook_file)
    else:
        workbook = Workbook()

    worksheet = workbook[sheet_name] if sheet_name and sheet_name in workbook.sheetnames else workbook.active
    header_row, header_map = _sheet_and_header_row(worksheet)
    header_map = _ensure_headers(worksheet, header_row, header_map)

    for row_index in range(header_row + 1, worksheet.max_row + 1):
        for column_index in range(1, max(header_map.values()) + 1):
            worksheet.cell(row=row_index, column=column_index).value = None

    jobs = [
        job
        for job in tracker.list_jobs(limit=None)
        if job.status in APPLIED_STATUSES and is_internship_listing(job)
    ]
    jobs.sort(key=lambda job: (job.updated_at, job.created_at), reverse=True)

    for row_offset, job in enumerate(jobs, start=1):
        row_index = header_row + row_offset
        values = {
            "company name": job.company,
            "job title": job.title,
            "link to job": job.apply_url or job.source_url or "",
            "job description": job.description or job.raw_text or "",
            "location": job.location or "",
            "status": _status_label(job),
            "company contact details": _contact_details(job),
            "date applied": _applied_at(tracker, job),
        }
        for column_name, value in values.items():
            worksheet.cell(row=row_index, column=header_map[_normalise(column_name)], value=value)

    header_fill = PatternFill(fill_type="solid", fgColor="1F2937")
    header_font = Font(color="FFFFFF", bold=True)
    for column_name in EXPORT_COLUMNS:
        cell = worksheet.cell(row=header_row, column=header_map[_normalise(column_name)])
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")

    worksheet.freeze_panes = worksheet.cell(row=header_row + 1, column=1)
    worksheet.auto_filter.ref = f"A{header_row}:{worksheet.cell(row=header_row, column=max(header_map.values())).coordinate}"

    for column_index in range(1, max(header_map.values()) + 1):
        column_letter = worksheet.cell(row=header_row, column=column_index).column_letter
        column_values = [worksheet.cell(row=row, column=column_index).value for row in range(1, worksheet.max_row + 1)]
        max_length = max((len(str(value)) for value in column_values if value is not None), default=0)
        worksheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 60)

    workbook.save(workbook_file)
    return workbook_file, len(jobs)
