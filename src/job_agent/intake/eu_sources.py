"""Loader and types for the packaged, offline EU source registry."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypedDict, cast


class EUSource(TypedDict):
    id: str
    name: str
    url: str
    countries: list[str]
    access_type: Literal["api", "rss", "manual-links"]
    requires_auth: bool
    license_posture: str
    notes: str
    added_date: str
    attribution: str
    verified: bool


class EUSourceRegistry(TypedDict):
    attribution: str
    sources: list[EUSource]


_REGISTRY_PATH = Path(__file__).parents[1] / "data" / "eu_sources.json"


def load_eu_source_registry() -> EUSourceRegistry:
    """Read the packaged registry without performing any network access."""
    with _REGISTRY_PATH.open(encoding="utf-8") as handle:
        return cast(EUSourceRegistry, json.load(handle))
