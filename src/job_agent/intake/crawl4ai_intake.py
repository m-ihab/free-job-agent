"""Careers-page intake via crawl4AI (optional dependency).

Pipeline: robots gate → crawl4AI page→markdown → deterministic link heuristics
→ :class:`JobListing` drafts (status ``DISCOVERED``, source ``crawl4ai``) that
flow through the normal filter/score pipeline. The extraction core is pure and
importable without crawl4ai installed; only :func:`fetch_page_markdown` needs
the library (``pip install free-job-agent[crawl]``).

Ethics contract (CLAUDE.md): public pages only, robots.txt respected,
no logged-in job boards, detection never circumvented.
"""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from job_agent.schemas.job import JobListing, JobStatus

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; FreeJobAgent/0.3; local-first job assistant)"

_MD_LINK = re.compile(r"\[([^\]]{3,160})\]\(<?([^)\s>]+)>?\)")
_TITLE_HINTS = (
    "data", "scientist", "science", "engineer", "ingénieur", "ingenieur",
    "machine learning", "ml ", "deep learning", " ai", "ai ", "analyst",
    "analytics", "analyste", "python", "nlp", "llm", "mlops",
    "stage", "stagiaire", "alternance", "alternant", "intern",
    "développeur", "developpeur", "developer",
)
_EXCLUDE_HINTS = (
    "privacy", "cookie", "cookies", "login", "log in", "sign in", "sign up",
    "about us", "contact", "blog", "press", "legal", "mentions légales",
    "linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com",
    "read more", "learn more", "see all", "home",
)


def _load_crawl4ai():
    """Import seam so tests can simulate the library being absent/present."""
    try:
        from crawl4ai import AsyncWebCrawler  # type: ignore

        return AsyncWebCrawler
    except Exception:
        return None


def robots_allows(url: str, *, user_agent: str = USER_AGENT, timeout: int = 10) -> bool:
    """True unless robots.txt explicitly disallows ``url`` for our agent.

    Fail-open on robots fetch errors (public careers pages routinely lack
    robots.txt); fail-closed only on an explicit disallow rule.
    """
    from job_agent.utils.net import safe_get

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = safe_get(robots_url, headers={"User-Agent": user_agent}, timeout=timeout)
        if response.status_code >= 400:
            return True
        parser = RobotFileParser()
        parser.parse((response.text or "").splitlines())
        return parser.can_fetch(user_agent, url)
    except Exception:
        return True


def fetch_page_markdown(url: str, *, timeout: int = 40) -> str | None:
    """Render ``url`` (JS included) to clean markdown via crawl4AI. None on failure."""
    crawler_cls = _load_crawl4ai()
    if crawler_cls is None:
        logger.info("crawl4ai not installed; install with `pip install 'free-job-agent[crawl]'`")
        return None

    async def _run() -> str | None:
        async with crawler_cls() as crawler:
            result = await crawler.arun(url=url)
            markdown = getattr(result, "markdown", None)
            return str(markdown) if markdown else None

    try:
        return asyncio.run(asyncio.wait_for(_run(), timeout=timeout))
    except Exception as exc:
        logger.warning("crawl4ai fetch failed for %s: %s", url, exc)
        return None


def looks_like_job_title(text: str) -> bool:
    """Cheap language-aware gate for 'this link is probably a job posting'."""
    lowered = f" {(text or '').strip().lower()} "
    if not 3 <= len(lowered.strip()) <= 140:
        return False
    if any(hint in lowered for hint in _EXCLUDE_HINTS):
        return False
    return any(hint in lowered for hint in _TITLE_HINTS)


def extract_job_links(markdown: str, base_url: str) -> list[tuple[str, str]]:
    """Extract (title, absolute_url) pairs that look like job postings."""
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _MD_LINK.finditer(markdown or ""):
        title = re.sub(r"[#*_`]+", "", match.group(1)).strip()
        href = match.group(2).strip()
        absolute = urljoin(base_url, href)
        if urlparse(absolute).scheme not in {"http", "https"}:
            continue
        if absolute in seen or not looks_like_job_title(title):
            continue
        seen.add(absolute)
        results.append((title, absolute))
        if len(results) >= 100:
            break
    return results


def listings_from_links(
    links: list[tuple[str, str]], *, company: str, source_url: str
) -> list[JobListing]:
    """Turn extracted links into DISCOVERED drafts for the normal pipeline."""
    listings: list[JobListing] = []
    for title, url in links:
        listings.append(
            JobListing(
                source="crawl4ai",
                source_url=source_url,
                apply_url=url,
                title=title,
                company=company,
                raw_text=title,
                status=JobStatus.DISCOVERED,
            )
        )
    return listings


def _company_from_url(url: str) -> str:
    host = urlparse(url).netloc.split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    return (host.split(".")[0] or "Unknown").capitalize()


def crawl_careers_page(
    url: str,
    *,
    company: str | None = None,
    respect_robots: bool = True,
    timeout: int = 40,
    max_jobs: int = 40,
) -> list[JobListing]:
    """Crawl one public careers page into JobListing drafts. Empty list on failure."""
    if respect_robots and not robots_allows(url):
        logger.info("robots.txt disallows %s — skipping (fail-closed)", url)
        return []
    markdown = fetch_page_markdown(url, timeout=timeout)
    if not markdown:
        return []
    links = extract_job_links(markdown, url)[: max(0, max_jobs)]
    return listings_from_links(links, company=company or _company_from_url(url), source_url=url)
