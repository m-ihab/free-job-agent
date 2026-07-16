"""Thin dashboard routes for CLI features that lacked a visible surface."""
from __future__ import annotations

import base64
import binascii
import tempfile
import zipfile
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from job_agent.db.database import Database
from job_agent.evidence import EvidenceStore
from job_agent.intake.france_market import cac40_targets
from job_agent.intake.profile_import import ProfileImportError, parse_profile_import
from job_agent.tracker import ApplicationTracker

_ALLOWED_PROFILE_SUFFIXES = {".json", ".zip"}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_MAX_ZIP_CONTENT_BYTES = 50 * 1024 * 1024


def get_france_targets(h: Any) -> None:
    """Return curated company career targets already used by the CLI."""
    try:
        raw = (parse_qs(urlparse(h.path).query).get("limit") or ["40"])[0]
        limit = int(raw)
        if not 1 <= limit <= 100:
            raise ValueError
    except (TypeError, ValueError):
        return h._send_error_json("limit must be an integer between 1 and 100")
    targets = [
        {"company": item.name, "sector": item.sector, "url": item.careers_url}
        for item in cac40_targets(limit=limit)
    ]
    h._send_json({"targets": targets})


def get_job_history(h: Any) -> None:
    """Return the same per-job event history exposed by the CLI."""
    job_id = (parse_qs(urlparse(h.path).query).get("job_id") or [""])[0].strip()
    if not job_id:
        return h._send_error_json("job_id is required.")
    db = Database(h._config().db_path)
    db.initialize()
    tracker = ApplicationTracker(db)
    job = tracker.get_job(job_id)
    if not job:
        return h._send_error_json("Job not found.", HTTPStatus.NOT_FOUND)
    h._send_json({"job_id": job.id, "events": tracker.get_history(job.id)})


def post_profile_import(h: Any, payload: dict[str, Any]) -> None:
    """Decode a bounded local upload and reuse the grounded profile importer."""
    filename = Path(str(payload.get("filename") or "")).name
    encoded = str(payload.get("content_base64") or "")
    suffix = Path(filename).suffix.casefold()
    if not filename or not encoded:
        return h._send_error_json("filename and content_base64 are required.")
    if suffix not in _ALLOWED_PROFILE_SUFFIXES:
        return h._send_error_json("Profile import must be a .json or .zip file.")
    if len(encoded) > (_MAX_UPLOAD_BYTES * 4 // 3) + 4:
        return h._send_error_json("Profile import is too large (10 MB maximum).")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return h._send_error_json("Profile import content is not valid base64.")
    if len(content) > _MAX_UPLOAD_BYTES:
        return h._send_error_json("Profile import is too large (10 MB maximum).")

    try:
        with tempfile.TemporaryDirectory(prefix="job-agent-profile-") as temp_dir:
            path = Path(temp_dir) / filename
            path.write_bytes(content)
            _validate_zip_size(path)
            result = parse_profile_import(path)
    except (OSError, ProfileImportError, zipfile.BadZipFile) as exc:
        return h._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)

    stored = EvidenceStore.load(h._config()).merge(result.entries)
    h._send_json(
        {
            "input_type": result.input_type,
            "parsed": len(result.entries),
            "stored": stored,
            "section_counts": result.section_counts,
            "missing_sections": result.missing_sections,
        }
    )


def _validate_zip_size(path: Path) -> None:
    if path.suffix.casefold() != ".zip" or not zipfile.is_zipfile(path):
        return
    with zipfile.ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > _MAX_ZIP_CONTENT_BYTES:
            raise ProfileImportError("LinkedIn export expands beyond the 50 MB safety limit.")
