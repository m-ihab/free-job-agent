"""Utilities for enrichment parameter templates and payload parsing."""
from __future__ import annotations

import re
from typing import Any

from job_agent.schemas.job import JobListing


def build_context(job: JobListing) -> dict[str, str]:
    location = job.location or ""
    department = extract_department(location)
    siret = extract_siret(job)
    siren = siret[:9] if siret and len(siret) >= 9 else ""
    return {
        "title": job.title or "",
        "company": job.company or "",
        "location": location,
        "department": department,
        "siret": siret,
        "siren": siren,
    }


def extract_department(location: str) -> str:
    if not location:
        return ""
    match = re.search(r"\b(\d{2,3})\b", location)
    return match.group(1) if match else ""


def extract_siret(job: JobListing) -> str:
    text = "\n".join([job.description or "", job.raw_text or ""])
    match = re.search(r"\b\d{14}\b", text)
    return match.group(0) if match else ""


def fill_params(params: dict[str, Any], context: dict[str, str]) -> dict[str, Any]:
    rendered: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if isinstance(value, str):
            rendered[key] = value.format_map(context)
        else:
            rendered[key] = value
    return {k: v for k, v in rendered.items() if v not in (None, "", [])}


def extract_labels(payload: Any, *, limit: int = 12) -> list[str]:
    labels: list[str] = []

    def add(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text and text not in labels:
                labels.append(text)
            return
        if isinstance(value, dict):
            for key in ("libelle", "label", "name", "title", "nom"):
                if key in value:
                    add(value.get(key))
                    return
            for inner in value.values():
                add(inner)
            return
        if isinstance(value, list):
            for item in value:
                add(item)
            return

    add(payload)
    return labels[:limit]


def extract_best_string(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("description", "definition", "libelle", "label", "name", "title", "nom"):
            if key in payload and isinstance(payload[key], str):
                return payload[key].strip()
        for value in payload.values():
            text = extract_best_string(value)
            if text:
                return text
    if isinstance(payload, list):
        for item in payload:
            text = extract_best_string(item)
            if text:
                return text
    return ""


def extract_numeric(payload: Any) -> float | None:
    if isinstance(payload, (int, float)):
        return float(payload)
    if isinstance(payload, dict):
        for key in ("rating", "note", "score", "moyenne", "average"):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value.replace(",", "."))
                except ValueError:
                    pass
        for value in payload.values():
            found = extract_numeric(value)
            if found is not None:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = extract_numeric(item)
            if found is not None:
                return found
    return None
