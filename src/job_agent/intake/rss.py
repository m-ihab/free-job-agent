"""Ingest job listings from an RSS/Atom feed."""
from __future__ import annotations

from typing import Optional
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from job_agent.schemas.job import JobListing
from job_agent.utils.html import strip_html
from job_agent.utils.net import safe_get

try:  # pragma: no cover - optional dependency
    import feedparser  # type: ignore
except Exception:  # pragma: no cover
    feedparser = SimpleNamespace(parse=lambda feed_url: SimpleNamespace(entries=[]))


def _strip_html(html: str) -> str:
    return strip_html(html or "", separator="\n")


def _ingest_rss_fallback(feed_url: str, limit: Optional[int] = None) -> list[JobListing]:
    resp = safe_get(feed_url, timeout=20)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    jobs: list[JobListing] = []
    for item in items[:limit] if limit else items:
        def find_text(names: list[str]) -> str:
            for name in names:
                node = item.find(name) or item.find(f"{{http://www.w3.org/2005/Atom}}{name}")
                if node is not None and node.text:
                    return node.text
            return ""
        title = find_text(["title"]) or "[To Be Parsed]"
        summary = find_text(["description", "summary", "content"])
        link = find_text(["link"])
        if not link:
            link_node = item.find("{http://www.w3.org/2005/Atom}link")
            if link_node is not None:
                link = link_node.attrib.get("href", "")
        raw_text = _strip_html("\n".join([title, summary]))
        jobs.append(JobListing(source="rss", source_url=link or None, apply_url=link or None, raw_text=raw_text, title=title, company="[To Be Parsed]"))
    return jobs


def ingest_rss(feed_url: str, limit: Optional[int] = None) -> list[JobListing]:
    feed = feedparser.parse(feed_url)
    if not getattr(feed, "entries", None):
        try:
            return _ingest_rss_fallback(feed_url, limit=limit)
        except Exception:
            return []
    jobs: list[JobListing] = []
    entries = feed.entries[:limit] if limit else feed.entries
    for entry in entries:
        raw_parts = [entry.get("title", ""), entry.get("summary", "") or entry.get("description", "")]
        if hasattr(entry, "content"):
            for c in entry.content:
                raw_parts.append(c.get("value", ""))
        raw_text = _strip_html("\n".join(p for p in raw_parts if p))
        link = entry.get("link", None)
        jobs.append(JobListing(source="rss", source_url=link, apply_url=link, raw_text=raw_text, title=entry.get("title", "[To Be Parsed]"), company="[To Be Parsed]"))
    return jobs
