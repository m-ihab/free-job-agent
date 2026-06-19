"""Heuristic relevance scoring for search cleanup.

This module is intentionally conservative: it does not replace the main fit
scorer or local AI analysis. It only helps the search layer keep obvious noise
out of one-click imports while still allowing broad search when the user wants
it.
"""
from __future__ import annotations

import re
from typing import Any

from job_agent.intake.internships import is_internship_listing
from job_agent.schemas.job import JobListing


ROLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "data_science": (
        r"\bdata scientist\b",
        r"\bdata science\b",
        r"\bscience des donn[eé]es\b",
        r"\bscientifique des donn[eé]es\b",
        r"\bstatisticien\b",
    ),
    "machine_learning": (
        r"\bmachine learning\b",
        r"\bml engineer\b",
        r"\bing[eé]nieur ml\b",
        r"\bai engineer\b",
        r"\bia engineer\b",
        r"\bdata\b.*\bia\b",
        r"\bia\b.*\bdata\b",
        r"\bintelligence artificielle\b",
        r"\bdeep learning\b",
        r"\bllm\b",
    ),
    "data_engineering": (
        r"\bdata engineer\b",
        r"\bdata engineering\b",
        r"\bing[eé]nieur data\b",
        r"\betl\b",
        r"\bdata platform\b",
        r"\bdata pipeline",
    ),
    "data_analyst": (
        r"\bdata analyst\b",
        r"\banalyste de donn[eé]es\b",
        r"\banalyste data\b",
        r"\bbusiness intelligence\b",
        r"\bpower bi\b",
        r"\banalytics engineer\b",
    ),
}

GENERIC_DATA_SIGNALS = (
    r"\bpython\b",
    r"\bsql\b",
    r"\bpandas\b",
    r"\bscikit-learn\b",
    r"\btensorflow\b",
    r"\bpytorch\b",
    r"\bpower bi\b",
    r"\btableau\b",
    r"\bmlops\b",
    r"\bnlp\b",
    r"\bcomputer vision\b",
)

OFF_TOPIC_PATTERNS = (
    r"\bcancer registry\b",
    r"\bcancer data abstractor\b",
    r"\babstractor\b",
    r"\bchef(?:fe)? de produit\b",
    r"\bproduct owner\b",
    r"\bproduct manager\b",
    r"\bmarketing\b",
    r"\bmedia\b",
    r"\baffiliation\b",
    r"\bmaintenance industrielle\b",
    r"\brgpd\b",
    r"\bcybers[eé]curit[eé]\b",
    r"\bpricing analyst\b",
    r"\bcommercial\b",
    r"\bsales\b",
    r"\brecruiter\b",
    r"\bdevops engineer\b",
)

BARRIER_PATTERNS = (
    r"\bphd\b",
    r"\bdoctorat\b",
    r"\bpost-?doc\b",
    r"\bpostdoctoral\b",
    r"\bsenior\b",
    r"\blead\b",
    r"\bprincipal\b",
    r"\bstaff\b",
    r"\b5\+?\s*(?:years|ans)\b",
)

NON_EU_LOCATION_PATTERNS = (
    r"\bunited states\b",
    r"\busa\b",
    r"\bcanada\b",
    r"\bargentina\b",
    r"\baustralia\b",
    r"\bnew zealand\b",
    r"\bindia\b",
    r"\bsingapore\b",
    r"\bsouth africa\b",
    r"\bisrael\b",
    r"\buae\b",
)


# Pre-compiled mirrors of the pattern tuples above. The string definitions are
# kept as the readable source of truth; these compiled versions avoid
# re-parsing the same patterns on every per-job call in the hot search path.
_ROLE_PATTERNS_C: dict[str, tuple[re.Pattern[str], ...]] = {
    family: tuple(re.compile(p, re.IGNORECASE) for p in patterns)
    for family, patterns in ROLE_PATTERNS.items()
}
_GENERIC_DATA_SIGNALS_C: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in GENERIC_DATA_SIGNALS
)
_OFF_TOPIC_PATTERNS_C: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in OFF_TOPIC_PATTERNS
)
_BARRIER_PATTERNS_C: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in BARRIER_PATTERNS
)
_NON_EU_LOCATION_PATTERNS_C: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in NON_EU_LOCATION_PATTERNS
)


def _text(job: JobListing, *, include_description: bool = True) -> str:
    parts = [
        job.title,
        job.company,
        job.location or "",
        job.job_type or "",
        " ".join(job.tech_stack),
    ]
    if include_description:
        parts.extend([job.description or "", job.raw_text or ""])
    return "\n".join(str(part or "") for part in parts).casefold()


def _matches(patterns: tuple[re.Pattern[str], ...], text: str) -> list[re.Pattern[str]]:
    return [pattern for pattern in patterns if pattern.search(text)]


def detect_role_family(job: JobListing) -> str:
    title_text = (job.title or "").casefold()
    full_text = _text(job)
    for family, patterns in _ROLE_PATTERNS_C.items():
        if _matches(patterns, title_text):
            return family
    for family, patterns in _ROLE_PATTERNS_C.items():
        if _matches(patterns, full_text):
            return family
    return ""


def detect_contract_family(job: JobListing) -> str:
    text = _text(job)
    if is_internship_listing(job):
        if re.search(r"\b(alternance|apprentissage|apprenti|apprenticeship)\b", text):
            return "alternance"
        return "stage"
    if re.search(r"\b(cdi|permanent|full[- ]time|temps plein)\b", text):
        return "cdi"
    if re.search(r"\b(cdd|contract|freelance)\b", text):
        return "contract"
    return ""


def is_france_or_eu_location(job: JobListing) -> bool:
    location = (job.location or "").casefold()
    if not location:
        return True
    return not any(pattern.search(location) for pattern in _NON_EU_LOCATION_PATTERNS_C)


def assess_search_quality(job: JobListing, *, query: str = "", location: str = "") -> dict[str, Any]:
    """Return a small relevance payload used by the UI and search imports."""
    title_text = (job.title or "").casefold()
    full_text = _text(job)
    family = detect_role_family(job)
    contract = detect_contract_family(job)
    flags: list[str] = []
    score = 0

    if family:
        score += 55 if _matches(_ROLE_PATTERNS_C[family], title_text) else 35
    else:
        generic_hits = sum(1 for pattern in _GENERIC_DATA_SIGNALS_C if pattern.search(full_text))
        if re.search(r"\bdata\b", title_text) and generic_hits:
            score += 30
        elif re.search(r"\bdata\b", title_text):
            score += 15
            flags.append("generic-data-title")

    if contract in {"stage", "alternance"}:
        score += 15
    elif contract == "cdi":
        score += 5

    generic_hits = sum(1 for pattern in _GENERIC_DATA_SIGNALS_C if pattern.search(full_text))
    score += min(20, generic_hits * 4)

    if job.remote or is_france_or_eu_location(job):
        score += 10
    else:
        score -= 30
        flags.append("outside-target-region")

    if location and location.casefold() in {"paris", "ile-de-france", "idf", "france"} and not is_france_or_eu_location(job):
        score -= 25

    off_topic = _matches(_OFF_TOPIC_PATTERNS_C, title_text)
    if off_topic:
        score -= 45
        flags.append("off-topic-title")

    barriers = _matches(_BARRIER_PATTERNS_C, full_text)
    if barriers:
        score -= 20
        flags.append("seniority-or-degree-barrier")

    query_text = query.casefold()
    if query_text:
        query_family_hits = [
            family_name
            for family_name, patterns in _ROLE_PATTERNS_C.items()
            if any(pattern.search(query_text) for pattern in patterns)
        ]
        if query_family_hits and family and family not in query_family_hits:
            score -= 10

    score = max(0, min(100, score))
    return {
        "score": score,
        "role_family": family,
        "contract": contract,
        "flags": sorted(set(flags)),
        "relevant": score >= 50 and "off-topic-title" not in flags,
    }


def is_search_relevant(job: JobListing, *, query: str = "", location: str = "", minimum: int = 50) -> bool:
    quality = assess_search_quality(job, query=query, location=location)
    return bool(quality["relevant"]) and int(quality["score"]) >= minimum
