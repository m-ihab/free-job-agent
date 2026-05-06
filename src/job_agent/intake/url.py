"""Ingest job description from a public URL."""
from __future__ import annotations

import requests
from bs4 import BeautifulSoup

from job_agent.schemas.job import JobListing

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; FreeJobAgent/0.1; +https://github.com/m-ihab/free-job-agent)"
    )
}


def ingest_url(url: str, timeout: int = 15) -> JobListing:
    """Fetch a public job page and extract visible text."""
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return JobListing(
        source="url",
        source_url=url,
        raw_text=text.strip(),
        title="[To Be Parsed]",
        company="[To Be Parsed]",
    )
