"""Link score components to concrete rows from the local evidence store."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from job_agent.schemas.job import JobListing
from job_agent.utils import fuzzy

_NO_EVIDENCE = "No supporting evidence found in the evidence store."
_STORE_UNAVAILABLE = "Evidence store unavailable; no evidence linked."
_SNIPPET_LIMIT = 140


def link_score_evidence(
    explanation: dict[str, Any],
    job: JobListing,
    evidence_items: Iterable[Mapping[str, Any]],
    *,
    store_available: bool = True,
) -> dict[str, Any]:
    """Add evidence metadata without changing existing explanation fields."""
    items = list(evidence_items)
    for component in explanation.get("components", []):
        matches = _matches_for_component(str(component.get("name") or ""), job, items)
        component["evidence"] = [_payload(item) for item in matches]
        if matches:
            count = len(matches)
            suffix = "entry" if count == 1 else "entries"
            component["evidence_label"] = f"{count} supporting evidence {suffix}."
        else:
            component["evidence_label"] = _NO_EVIDENCE if store_available else _STORE_UNAVAILABLE
    return explanation


def _matches_for_component(
    name: str,
    job: JobListing,
    items: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    if name == "skill":
        return _matching_rows(items, "skill", job.tech_stack)
    if name == "language":
        return _matching_rows(items, "language", _required_languages(job))
    return []


def _matching_rows(
    items: list[Mapping[str, Any]],
    kind: str,
    terms: Iterable[str],
) -> list[Mapping[str, Any]]:
    needles = [_normalise(term) for term in terms if _normalise(term)]
    result: list[Mapping[str, Any]] = []
    for item in items:
        if item.get("id") is None or str(item.get("kind") or "") != kind:
            continue
        haystack = _normalise(f"{item.get('label', '')} {item.get('value', '')}")
        if any(_term_matches(needle, haystack) for needle in needles):
            result.append(item)
    return result


def _required_languages(job: JobListing) -> list[str]:
    languages = list(job.languages or [])
    text = f"{job.title} {job.description}".casefold()
    french_signals = (
        "french required",
        "francais requis",
        "niveau c1",
        "niveau c2",
        "bilingue francais",
        "courant en francais",
        "french fluent",
        "langue francaise",
        "parler francais",
    )
    if any(signal in text for signal in french_signals):
        languages.extend(["french", "francais"])
    return languages


def _term_matches(needle: str, haystack: str) -> bool:
    if f" {needle} " in f" {haystack} ":
        return True
    return (
        fuzzy.ratio(needle, haystack) >= 85
        or fuzzy.partial_ratio(needle, haystack) >= 90
    )


def _payload(item: Mapping[str, Any]) -> dict[str, Any]:
    label = str(item.get("label") or "").strip()
    value = str(item.get("value") or "").strip()
    snippet = f"{label} — {value}" if value and value != label else label or value
    if len(snippet) > _SNIPPET_LIMIT:
        snippet = f"{snippet[: _SNIPPET_LIMIT - 1].rstrip()}…"
    source = str(item.get("source_ref") or item.get("source") or "unknown")
    return {"id": item["id"], "snippet": snippet, "source": source}


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
