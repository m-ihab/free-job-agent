"""Ingest job listings from an RSS/Atom feed."""
from __future__ import annotations

from typing import Optional

import feedparser
from bs4 import BeautifulSoup

from job_agent.schemas.job import JobListing


def _strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)


def ingest_rss(feed_url: str, limit: Optional[int] = None) -> list[JobListing]:
    """Parse an RSS/Atom feed and return a list of job listings."""
    feed = feedparser.parse(feed_url)
    jobs = []
    entries = feed.entries[:limit] if limit else feed.entries
    for entry in entries:
        raw_parts = [
            entry.get("title", ""),
            entry.get("summary", "") or entry.get("description", ""),
        ]
        if hasattr(entry, "content"):
            for c in entry.content:
                raw_parts.append(c.get("value", ""))
        raw_text = _strip_html("\n".join(p for p in raw_parts if p))
        job = JobListing(
            source="rss",
            source_url=entry.get("link", None),
            raw_text=raw_text,
            title=entry.get("title", "[To Be Parsed]"),
            company="[To Be Parsed]",
        )
        jobs.append(job)
    return jobs
