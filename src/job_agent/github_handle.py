"""GitHub handle validation shared by enrichment and portfolio imports."""
from __future__ import annotations

import re
from urllib.parse import urlparse

_GITHUB_HANDLE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def normalise_github_handle(value: str) -> str:
    """Return a GitHub username, or raise ``ValueError`` for malformed input."""
    raw = (value or "").strip().lstrip("@").rstrip("/")
    if not raw:
        raise ValueError("GitHub handle is required.")
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
            raise ValueError("GitHub URL must point to github.com.")
        parts = [part for part in parsed.path.split("/") if part]
        raw = parts[0] if parts else ""
    elif "/" in raw:
        raise ValueError("GitHub handle must not contain path separators.")
    if not _GITHUB_HANDLE_RE.fullmatch(raw):
        raise ValueError("GitHub handle contains invalid characters.")
    return raw
