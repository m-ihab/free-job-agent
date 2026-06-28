"""Small route-registry accessors for tests and tooling."""
from __future__ import annotations

from collections.abc import Callable

from job_agent.ui.routes import GET_ROUTES, POST_ROUTES


def get_routes() -> dict[str, Callable]:
    return dict(GET_ROUTES)


def post_routes() -> dict[str, Callable]:
    return dict(POST_ROUTES)


def route_summary() -> dict[str, list[str]]:
    return {
        "GET": sorted(GET_ROUTES),
        "POST": sorted(POST_ROUTES),
    }


__all__ = ["get_routes", "post_routes", "route_summary"]
