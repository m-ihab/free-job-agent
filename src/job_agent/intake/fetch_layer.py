"""Adaptive static-fetch layer: Scrapling when installed, hardened requests fallback.

Scrapling's value here is resilient fetching/parsing for public job pages; its
stealth / anti-bot-bypass modes are deliberately NOT used — the project rule is
"detection allowed, circumvention not" (CLAUDE.md fail-closed ethics). The
fallback path uses :func:`job_agent.utils.net.safe_get`, keeping the SSRF
defenses for user-influenced URLs.

Install the optional backend with ``pip install 'free-job-agent[scraping]'``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FreeJobAgent/0.3; local-first job assistant)"
}


@dataclass(frozen=True)
class FetchResult:
    """Backend-agnostic fetch outcome."""

    url: str
    status_code: int
    text: str
    backend: str  # scrapling | requests | error

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400 and bool(self.text)


def _load_scrapling():
    """Import seam so tests can simulate the library being absent/present."""
    try:
        from scrapling.fetchers import Fetcher  # type: ignore

        return Fetcher
    except Exception:
        return None


def _via_scrapling(fetcher: object, url: str, timeout: int) -> FetchResult:
    """Plain (non-stealth) Scrapling fetch, normalized across attribute names."""
    page = fetcher.get(url, timeout=timeout)  # type: ignore[attr-defined]
    status = getattr(page, "status", None) or getattr(page, "status_code", None) or 200
    text = (
        getattr(page, "html_content", None)
        or getattr(page, "body", None)
        or getattr(page, "text", None)
        or ""
    )
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return FetchResult(url=url, status_code=int(status), text=str(text), backend="scrapling")


def fetch_static(
    url: str, *, timeout: int = DEFAULT_TIMEOUT, headers: dict[str, str] | None = None
) -> FetchResult:
    """Fetch a public static page; never raises — inspect ``FetchResult.ok``."""
    fetcher = _load_scrapling()
    if fetcher is not None:
        try:
            return _via_scrapling(fetcher, url, timeout)
        except Exception as exc:
            logger.info("scrapling fetch failed (%s: %s); falling back to requests",
                        type(exc).__name__, exc)
    from job_agent.utils.net import safe_get

    try:
        response = safe_get(url, headers=headers or dict(HEADERS), timeout=timeout)
        return FetchResult(
            url=url,
            status_code=int(getattr(response, "status_code", 0) or 0),
            text=response.text or "",
            backend="requests",
        )
    except Exception as exc:
        logger.warning("fetch failed for %s: %s", url, exc)
        return FetchResult(url=url, status_code=0, text="", backend="error")
