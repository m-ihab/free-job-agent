"""Local CV template import helpers.

The project can truly tailor LaTeX because ``profiles/main.tex`` is editable
source. PDF/DOCX uploads are still useful, but they are stored as local
references/fallbacks rather than treated as perfectly editable templates.
"""
from __future__ import annotations

import base64
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from job_agent.config import AppConfig


SUPPORTED_TEMPLATE_EXTENSIONS = {".tex", ".pdf", ".docx", ".jpg", ".jpeg", ".png", ".sty", ".cls"}


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).name).strip()
    return cleaned or "uploaded_cv_template"


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.backup-{stamp}{path.suffix}")
    shutil.copyfile(path, backup)
    return backup


def import_cv_template_upload(config: AppConfig, *, filename: str, content_base64: str) -> dict:
    """Import an uploaded template into the local profiles directory."""
    profiles_dir = Path(config.profiles_dir)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(filename)
    ext = Path(safe_name).suffix.casefold()
    if ext not in SUPPORTED_TEMPLATE_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_TEMPLATE_EXTENSIONS))
        raise ValueError(f"Unsupported CV template type '{ext}'. Supported: {allowed}")
    try:
        data = base64.b64decode(content_base64, validate=True)
    except Exception as exc:
        raise ValueError("Invalid uploaded file content.") from exc
    if not data:
        raise ValueError("Uploaded file is empty.")
    if len(data) > 15 * 1024 * 1024:
        raise ValueError("Uploaded file is too large. Keep CV templates under 15 MB.")

    backups: list[str] = []
    note = ""
    if ext == ".tex":
        target = profiles_dir / "main.tex"
        backup = _backup(target)
        if backup:
            backups.append(str(backup))
        target.write_bytes(data)
        note = "LaTeX source imported as profiles/main.tex. Future CV tailoring will preserve this template."
    elif ext == ".pdf":
        target = profiles_dir / "CV.pdf"
        backup = _backup(target)
        if backup:
            backups.append(str(backup))
        target.write_bytes(data)
        note = "PDF stored as profiles/CV.pdf. It is used as a design-preserving fallback if LaTeX compilation fails."
    elif ext == ".docx":
        target = profiles_dir / "source_cv.docx"
        backup = _backup(target)
        if backup:
            backups.append(str(backup))
        target.write_bytes(data)
        note = "DOCX stored locally as profiles/source_cv.docx for reference. Use a .tex upload for fully editable tailoring."
    elif ext in {".jpg", ".jpeg"}:
        target = profiles_dir / "me.jpg"
        backup = _backup(target)
        if backup:
            backups.append(str(backup))
        target.write_bytes(data)
        note = "Photo imported as profiles/me.jpg for the LaTeX CV."
    elif ext == ".png":
        target = profiles_dir / "me.png"
        backup = _backup(target)
        if backup:
            backups.append(str(backup))
        target.write_bytes(data)
        note = "PNG photo stored as profiles/me.png. If your LaTeX expects me.jpg, upload a JPG too or update main.tex."
    else:
        target = profiles_dir / safe_name
        backup = _backup(target)
        if backup:
            backups.append(str(backup))
        target.write_bytes(data)
        note = f"{ext} support file stored next to main.tex."

    return {
        "ok": True,
        "target": str(target),
        "backups": backups,
        "note": note,
        "extension": ext,
    }
