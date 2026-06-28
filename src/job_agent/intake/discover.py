"""Discover likely job/application links on a public page."""
from __future__ import annotations

from urllib.parse import urljoin

from job_agent.utils.html import extract_links
from job_agent.utils.net import safe_get
from .url import HEADERS

JOB_LINK_KEYWORDS = ["job", "career", "position", "opening", "apply", "greenhouse", "lever", "workday", "ashby"]


def discover_job_links(url: str, timeout: int = 15, limit: int = 100) -> list[str]:
    resp = safe_get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    links: list[str] = []
    seen: set[str] = set()
    for anchor in extract_links(resp.text):
        text = f"{anchor.text} {anchor.href}".lower()
        if any(k in text for k in JOB_LINK_KEYWORDS):
            link = urljoin(url, anchor.href)
            if link not in seen:
                links.append(link)
                seen.add(link)
        if len(links) >= limit:
            break
    return links
