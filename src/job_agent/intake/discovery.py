"""Credential-less career-page discovery via ATS slug probing.

Given a company name, generate likely board slugs and probe the FREE public
ATS APIs the app already knows how to search (Greenhouse, Lever, Ashby,
Recruitee, Workable, SmartRecruiters, Personio). A 200 means the company runs
that ATS — the board is saved locally in ``company_boards`` and can then be
hunted with the existing ``search-api``/multi-search machinery.

This is the JobCopilot "official career pages only" model with zero scraping:
one polite HEAD/GET per (source, slug), sequential, negative results cached in
``broken_sources`` so repeat runs don't re-hammer dead slugs.
"""
from __future__ import annotations

import logging
import time
import unicodedata
from typing import Any, Callable

try:
    import requests
except Exception:  # pragma: no cover - requests is in install_requires
    requests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 8
DEFAULT_DELAY_SECONDS = 0.5
_NEGATIVE_CACHE_HOURS = 7 * 24.0
_MAX_SLUGS_PER_COMPANY = 3

# (source, url template). All probes are plain GETs against public endpoints.
_PROBES: list[tuple[str, str]] = [
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
    ("lever", "https://api.lever.co/v0/postings/{slug}?limit=1"),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}"),
    ("recruitee", "https://{slug}.recruitee.com/api/offers/"),
    ("workable", "https://apply.workable.com/api/v1/widget/accounts/{slug}"),
    ("smartrecruiters", "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1"),
    ("personio", "https://{slug}.jobs.personio.de/xml"),
]

# Curated French tech / data seed pack (public knowledge; extend freely).
_FRENCH_TECH_COMPANIES = [
    "Doctolib", "BlaBlaCar", "Back Market", "Qonto", "Alan", "PayFit", "Swile",
    "Ledger", "Mirakl", "Contentsquare", "Dataiku", "Hugging Face", "Owkin",
    "Shift Technology", "ManoMano", "Vestiaire Collective", "OVHcloud",
    "Deezer", "Ekimetrics", "Artefact", "Deepki", "Pigment", "Spendesk",
    "Pennylane", "Malt", "Yousign", "Lucca", "Sorare", "Voodoo", "Ubisoft",
]

Transport = Callable[[str, int], int]


def default_target_companies() -> list[str]:
    """Curated French tech/data companies worth probing, deduplicated."""
    seen: set[str] = set()
    result: list[str] = []
    for company in _FRENCH_TECH_COMPANIES:
        if company.lower() not in seen:
            seen.add(company.lower())
            result.append(company)
    return result


def _ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def slug_candidates(company: str) -> list[str]:
    """Likely ATS slugs for a company name, most specific first."""
    folded = _ascii_fold(company or "").lower()
    cleaned = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in folded)
    words = cleaned.split()
    if not words:
        return []
    candidates = []
    if len(words) > 1:
        candidates.append("-".join(words))
        candidates.append("".join(words))
    candidates.append(words[0])
    unique: list[str] = []
    for slug in candidates:
        if slug and slug not in unique:
            unique.append(slug)
    return unique[:_MAX_SLUGS_PER_COMPANY]


def _http_status(url: str, timeout: int) -> int:
    if requests is None:
        raise RuntimeError("requests is not installed")
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "job-agent-local/1.0"})
    return int(response.status_code)


def discover_company_boards(
    db: Any,
    company: str,
    *,
    sources: list[str] | None = None,
    transport: Transport | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> list[dict]:
    """Probe every (source, slug) pair for one company. Returns discovered boards.

    Negative results are cached in ``broken_sources`` for a week so repeated
    discovery runs stay polite. Transport errors count as misses, not hits.
    """
    transport = transport or _http_status
    wanted = set(sources) if sources else None
    found: list[dict] = []
    for source, template in _PROBES:
        if wanted is not None and source not in wanted:
            continue
        for slug in slug_candidates(company):
            if db.is_source_broken(f"discover:{source}", slug):
                continue
            url = template.format(slug=slug)
            try:
                status = transport(url, timeout)
            except Exception:
                logger.debug("Probe failed for %s %s", source, slug, exc_info=True)
                continue
            finally:
                sleep(delay)
            if status == 200:
                db.save_company_board(company, source, slug)
                found.append({"company": company, "source": source, "slug": slug})
                break  # one slug hit per source is enough
            db.mark_source_broken(
                f"discover:{source}", slug,
                status_code=status, reason="discovery probe miss", hours=_NEGATIVE_CACHE_HOURS,
            )
    return found


def discover_boards(
    db: Any,
    companies: list[str],
    *,
    sources: list[str] | None = None,
    transport: Transport | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> dict:
    """Batch discovery over a company list. Returns a summary dict."""
    boards: list[dict] = []
    for company in companies:
        if not (company or "").strip():
            continue
        boards.extend(discover_company_boards(
            db, company.strip(), sources=sources, transport=transport,
            timeout=timeout, sleep=sleep, delay=delay,
        ))
    return {
        "companies_checked": len([c for c in companies if (c or "").strip()]),
        "boards_found": len(boards),
        "boards": boards,
    }
