"""Add several jobs in one shot from a pasted blob or a list of URLs.

The dashboard's single add-url / add-text routes handle one job at a time. This
helper splits a multi-job paste into individual postings and feeds each through
the existing single-job intake, accumulating a per-batch summary. Splitting
rules (first match wins):
  * explicit ``---`` separator lines, else
  * blank-line-separated blocks.
Any block that is just a URL line is added as a URL; everything else as text.
"""
from __future__ import annotations

import re
from typing import Any

from job_agent.config import AppConfig
from job_agent.pipeline import add_text_job, add_url_job
from job_agent.utils.net import UnsafeUrlError

_URL_LINE = re.compile(r"^https?://\S+$")
_SEPARATOR = re.compile(r"^\s*-{3,}\s*$", re.M)


def _split_blocks(text: str) -> list[str]:
    if _SEPARATOR.search(text):
        parts = _SEPARATOR.split(text)
    else:
        parts = re.split(r"\n\s*\n", text)
    return [part.strip() for part in parts if part.strip()]


def bulk_add_jobs(
    config: AppConfig,
    *,
    text: str = "",
    urls: list[str] | None = None,
) -> dict[str, Any]:
    """Add every job found in ``text`` / ``urls``; return a batch summary."""
    added = 0
    duplicates = 0
    errors: list[str] = []
    job_ids: list[str] = []

    def _record(job: Any, created: bool) -> None:
        nonlocal added, duplicates
        if created:
            added += 1
            job_ids.append(job.id)
        else:
            duplicates += 1

    def _add_url(url: str) -> None:
        try:
            job, created = add_url_job(config, url)
        except UnsafeUrlError as exc:
            errors.append(f"{url[:60]}: {exc}")
            return
        except Exception as exc:
            errors.append(f"{url[:60]}: {type(exc).__name__}: {exc}")
            return
        _record(job, created)

    def _add_text(block: str) -> None:
        try:
            job, created = add_text_job(config, block)
        except Exception as exc:
            errors.append(f"{block[:40]}…: {type(exc).__name__}: {exc}")
            return
        _record(job, created)

    for url in urls or []:
        clean = str(url).strip()
        if clean:
            _add_url(clean)

    for block in _split_blocks(text or ""):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines and all(_URL_LINE.match(line) for line in lines):
            for line in lines:
                _add_url(line)
        else:
            _add_text(block)

    return {
        "added": added,
        "duplicates": duplicates,
        "errors": errors,
        "job_ids": job_ids,
        "total": added + duplicates,
    }
