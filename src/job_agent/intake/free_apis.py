"""Free/public job-source API ingestion (facade).

This module is a thin compatibility facade. The implementation was decomposed
into the :mod:`job_agent.intake.sources` package — one module per provider
behind a common :class:`SourceClient` Protocol. This module re-exports the full
public surface so existing imports (``from job_agent.intake.free_apis import X``)
keep working unchanged.

These connectors are intentionally read-only. They fetch public job postings
from sources that expose unauthenticated JSON feeds, free-key APIs, or public
ATS job-board feeds and normalize them into :class:`JobListing` objects. They do
not create accounts, log in, bypass access controls, or submit applications.

Note on ``requests``: the symbol below is the live ``requests`` module. Tests
monkeypatch ``free_apis.requests.get`` / ``free_apis.requests.post``; because
this is the shared ``requests`` module singleton, every provider that calls
``requests.get`` / ``requests.post`` transitively observes the patch.
"""
from __future__ import annotations

import requests  # re-exported so tests can patch free_apis.requests.get/post

from job_agent.intake.sources import (
    DEFAULT_CACHE_TTL_HOURS,
    DEFAULT_TIMEOUT,
    MAX_LIMIT,
    FreeApiError,
    FreeApiMultiSearchParams,
    FreeApiSearch,
    FreeApiSearchParams,
    SourceClient,
    SourceInfo,
    canonical_source,
    search_all_free_sources,
    search_free_api_jobs,
    supported_source_names,
)
from job_agent.intake.sources.base import (
    _bounded_limit,
    _contains_location,
    _contains_query,
    _first_nonempty,
    _query_score,
)
from job_agent.intake.sources.registry import (
    KEYWORD_ONLY_SOURCES,
    SUPPORTED_SOURCES,
)

__all__ = [
    "DEFAULT_CACHE_TTL_HOURS",
    "DEFAULT_TIMEOUT",
    "MAX_LIMIT",
    "FreeApiError",
    "FreeApiSearch",
    "FreeApiSearchParams",
    "FreeApiMultiSearchParams",
    "SourceClient",
    "SourceInfo",
    "SUPPORTED_SOURCES",
    "KEYWORD_ONLY_SOURCES",
    "canonical_source",
    "supported_source_names",
    "search_free_api_jobs",
    "search_all_free_sources",
    "requests",
    # Private helpers re-exported for backwards-compatible imports/tests.
    "_bounded_limit",
    "_contains_location",
    "_contains_query",
    "_first_nonempty",
    "_query_score",
]
