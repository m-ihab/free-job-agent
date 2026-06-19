"""Ingest job description from a public URL."""
from __future__ import annotations

from job_agent.schemas.job import JobListing
from job_agent.utils.html import strip_html
from job_agent.utils.net import safe_get

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FreeJobAgent/0.2; local-first job assistant)"
}


def _extract_visible_text(html: str) -> str:
    return strip_html(
        html,
        blocked_tags={"script", "style", "nav", "footer", "header", "noscript"},
        separator="\n",
    )


def ingest_url(url: str, timeout: int = 15) -> JobListing:
    resp = safe_get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    text = _extract_visible_text(resp.text)
    return JobListing(
        source="url",
        source_url=url,
        apply_url=url,
        raw_text=text.strip(),
        title="[To Be Parsed]",
        company="[To Be Parsed]",
    )
