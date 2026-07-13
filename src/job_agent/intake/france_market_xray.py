"""Google X-Ray targets for manual-open ATS job searches."""
from __future__ import annotations

from urllib.parse import quote_plus


XRAY_NOTES = "Manual-open only Google X-Ray search; never scrape or automate logged-in pages."

ATS_XRAY_SITES: tuple[tuple[str, str, str], ...] = (
    ("xray-greenhouse", "Google X-Ray · Greenhouse", "boards.greenhouse.io"),
    ("xray-lever", "Google X-Ray · Lever", "jobs.lever.co"),
    ("xray-ashby", "Google X-Ray · Ashby", "jobs.ashbyhq.com"),
    ("xray-workable", "Google X-Ray · Workable", "apply.workable.com"),
    (
        "xray-smartrecruiters",
        "Google X-Ray · SmartRecruiters",
        "jobs.smartrecruiters.com",
    ),
    ("xray-workday", "Google X-Ray · Workday", "myworkdayjobs.com"),
    ("xray-recruitee", "Google X-Ray · Recruitee", "recruitee.com"),
    ("xray-personio", "Google X-Ray · Personio", "jobs.personio.com"),
)


def build_xray_url(site: str, query: str, location: str) -> str:
    """Build an encoded Google ``site:`` query with normalized quoted phrases."""
    phrases = []
    for value in (query, location):
        cleaned = " ".join(value.replace('"', " ").split())
        if cleaned:
            phrases.append(f'"{cleaned}"')
    expression = " ".join([f"site:{site}", *phrases])
    return f"https://www.google.com/search?q={quote_plus(expression)}"
