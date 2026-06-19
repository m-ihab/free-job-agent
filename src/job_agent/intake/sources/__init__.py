"""Free/public job-source API connectors.

Each provider lives in its own module and exposes a ``fetch(search)`` callable
matching the :class:`SourceClient` Protocol. Dispatch, the source registry, and
the public ``search_*`` functions live in :mod:`registry`.

These connectors are intentionally read-only. They fetch public job postings
from sources that expose unauthenticated JSON feeds, free-key APIs, or public
ATS job-board feeds and normalize them into :class:`JobListing` objects. They do
not create accounts, log in, bypass access controls, or submit applications.
"""
from __future__ import annotations

from .base import (
    DEFAULT_CACHE_TTL_HOURS,
    DEFAULT_TIMEOUT,
    MAX_LIMIT,
    FreeApiError,
    FreeApiSearch,
    SourceClient,
    SourceInfo,
    _bounded_limit,
    _contains_location,
    _contains_query,
    _first_nonempty,
    _query_score,
)
from .registry import (
    KEYWORD_ONLY_SOURCES,
    SUPPORTED_SOURCES,
    FreeApiMultiSearchParams,
    FreeApiSearchParams,
    canonical_source,
    search_all_free_sources,
    search_free_api_jobs,
    supported_source_names,
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
    # Private helpers re-exported for backwards-compatible imports
    # (job_agent.intake.free_apis facade and existing tests).
    "_bounded_limit",
    "_contains_location",
    "_contains_query",
    "_first_nonempty",
    "_query_score",
]
