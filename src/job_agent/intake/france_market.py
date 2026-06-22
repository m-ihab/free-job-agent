"""France/Paris-focused job discovery helpers.

This module intentionally avoids scraping logged-in job boards. It provides:
- safe search URL generation for French job boards and CAC 40 career pages
- France/Paris default data/AI queries
- a curated, editable list of CAC 40 target companies/career pages

The query/board/company data lives in :mod:`france_market_queries` and
:mod:`france_market_boards`; this module holds the functions and re-exports the
data so existing ``from job_agent.intake.france_market import ...`` keeps working.
"""
from __future__ import annotations

import re

from job_agent.intake.france_market_boards import (
    CAC40_TARGETS,
    FRENCH_SEARCH_BOARDS,
    CompanyTarget,
    SearchBoard,
)
from job_agent.intake.france_market_queries import (
    DEFAULT_FRANCE_DATA_AI_QUERIES,
    ENGLISH_INTERNSHIP_QUERY_TERMS,
    ENGLISH_ROLE_QUERY_TERMS,
    FRENCH_INTERNSHIP_QUERY_TERMS,
    FRENCH_ROLE_QUERY_TERMS,
    INTERNSHIP_QUERY_TERMS,
    PARIS_LOCATION_ALIASES,
    ROLE_FAMILY_MAP,
    ROLE_QUERY_TERMS,
)


def build_france_search_urls(
    query: str,
    location: str = "Paris",
    boards: list[str] | None = None,
    recommended_only: bool = False,
) -> list[tuple[str, str, str]]:
    """Return (key, board name, URL) for manual job-board searches."""
    allowed = {b.casefold() for b in boards} if boards else None
    rows: list[tuple[str, str, str]] = []
    for board in FRENCH_SEARCH_BOARDS:
        if recommended_only and not board.recommended:
            continue
        if allowed and board.key.casefold() not in allowed and board.name.casefold() not in allowed:
            continue
        rows.append((board.key, board.name, board.url(query, location)))
    return rows


def _language_terms(language: str) -> tuple[list[str], list[str]]:
    language_key = (language or "both").strip().casefold()
    if language_key in {"en", "english"}:
        return ENGLISH_ROLE_QUERY_TERMS, ENGLISH_INTERNSHIP_QUERY_TERMS
    if language_key in {"fr", "french"}:
        return FRENCH_ROLE_QUERY_TERMS, FRENCH_INTERNSHIP_QUERY_TERMS
    return (
        ENGLISH_ROLE_QUERY_TERMS + [role for role in FRENCH_ROLE_QUERY_TERMS if role not in ENGLISH_ROLE_QUERY_TERMS],
        ENGLISH_INTERNSHIP_QUERY_TERMS + FRENCH_INTERNSHIP_QUERY_TERMS,
    )


def expand_role_family(query: str) -> list[str]:
    """If the seed query is a known role, return the related role variants.

    Otherwise return ``[query]``. Used by the autopilot's smart-query
    expansion so a user-entered seed like ``data scientist`` automatically
    also tries ``data engineer``, ``ml engineer``, ``ai engineer``, etc.
    """
    key = " ".join(query.split()).strip().casefold()
    if not key:
        return []
    for family_seed, variants in ROLE_FAMILY_MAP.items():
        if family_seed == key or family_seed in key:
            return list(variants)
    return [query.strip()]


def expand_france_search_queries(query: str, limit: int = 28, language: str = "both") -> list[str]:
    """Build bilingual internship/apprenticeship query variants for France."""
    base = " ".join(query.split()).strip()
    role_terms, contract_terms = _language_terms(language)
    variants: list[str] = []

    def add(value: str) -> None:
        cleaned = " ".join(value.split()).strip()
        seen = {item.casefold() for item in variants}
        if cleaned and cleaned.casefold() not in seen:
            variants.append(cleaned)

    add(base)
    base_lower = base.casefold()
    has_role = any(role.casefold() in base_lower for role in ROLE_QUERY_TERMS)
    has_contract = any(term.casefold() in base_lower for term in INTERNSHIP_QUERY_TERMS)

    if "data" in base_lower and not has_contract:
        # France Travail often performs better with short French query order
        # such as "stage data" than with literal English role order.
        add("stage data")
        add("alternance data")
        add("apprentissage data")

    if has_role and not has_contract:
        for term in contract_terms:
            add(f"{base} {term}")
            if term in FRENCH_INTERNSHIP_QUERY_TERMS:
                add(f"{term} {base}")
        if "data" in base_lower:
            for term in ["stage", "alternance", "apprentissage"]:
                add(f"{term} data")
                add(f"{term} data science")
    elif has_contract and not has_role:
        for role in role_terms:
            add(f"{role} {base}")
    elif has_role and has_contract:
        role_part = base
        for existing_term in INTERNSHIP_QUERY_TERMS:
            role_part = re.sub(rf"\b{re.escape(existing_term)}\b", "", role_part, flags=re.IGNORECASE)
        role_part = " ".join(role_part.split()) or base
        for term in contract_terms:
            add(f"{role_part} {term}")
    else:
        preferred_terms = [term for term in contract_terms if term in {"internship", "stage", "alternance"}] or contract_terms[:3]
        for role in role_terms:
            for term in preferred_terms:
                add(f"{role} {term}")
    return variants[:limit]


def board_notes() -> dict[str, str]:
    return {board.key: board.notes for board in FRENCH_SEARCH_BOARDS}


def recommended_board_keys() -> list[str]:
    return [board.key for board in FRENCH_SEARCH_BOARDS if board.recommended]


def cac40_targets(limit: int | None = None) -> list[CompanyTarget]:
    return CAC40_TARGETS if limit is None else CAC40_TARGETS[:limit]


__all__ = [
    # data (re-exported for backward compatibility)
    "ROLE_QUERY_TERMS",
    "ENGLISH_ROLE_QUERY_TERMS",
    "FRENCH_ROLE_QUERY_TERMS",
    "INTERNSHIP_QUERY_TERMS",
    "ENGLISH_INTERNSHIP_QUERY_TERMS",
    "FRENCH_INTERNSHIP_QUERY_TERMS",
    "DEFAULT_FRANCE_DATA_AI_QUERIES",
    "PARIS_LOCATION_ALIASES",
    "ROLE_FAMILY_MAP",
    "SearchBoard",
    "FRENCH_SEARCH_BOARDS",
    "CompanyTarget",
    "CAC40_TARGETS",
    # functions
    "build_france_search_urls",
    "expand_role_family",
    "expand_france_search_queries",
    "board_notes",
    "recommended_board_keys",
    "cac40_targets",
]
