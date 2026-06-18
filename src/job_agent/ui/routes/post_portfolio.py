"""POST handlers for the portfolio builder routes."""
from __future__ import annotations

from job_agent.portfolio_builder import (
    fetch_github_repos as _portfolio_github_repos,
    generate_portfolio as _portfolio_generate,
    generate_tagline as _portfolio_tagline,
    import_repos_to_portfolio as _portfolio_import_repos,
    portfolio_suggestions as _portfolio_suggest,
    publish_guide as _portfolio_publish_guide,
    save_portfolio as _portfolio_save,
)
from job_agent.ui.route_helpers import _resolve_github_handle


def post_portfolio_generate(h, payload) -> None:
    config = h._config()
    sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else None
    h._send_json(_portfolio_generate(
        config,
        theme=str(payload.get("theme") or "signal"),
        font=str(payload.get("font") or "inter"),
        layout=str(payload.get("layout") or "split"),
        custom_accent=str(payload.get("custom_accent") or ""),
        tagline=str(payload.get("tagline") or ""),
        site_url=str(payload.get("site_url") or ""),
        site_title_suffix=str(payload.get("site_title_suffix") or "Portfolio"),
        sections=sections,
        enable_dark_toggle=bool(payload.get("enable_dark_toggle", True)),
        enable_animations=bool(payload.get("enable_animations", True)),
    ))


def post_portfolio_save(h, payload) -> None:
    config = h._config()
    h._send_json(_portfolio_save(
        config,
        str(payload.get("html") or ""),
        str(payload.get("css") or ""),
    ))


def post_portfolio_suggest(h, payload) -> None:
    h._send_json(_portfolio_suggest(h._config()))


def post_portfolio_tagline(h, payload) -> None:
    h._send_json(_portfolio_tagline(h._config()))


def post_portfolio_github_repos(h, payload) -> None:
    config = h._config()
    handle = _resolve_github_handle(config, payload)
    if not handle:
        return h._send_error_json("Set contact.github_url first or pass `handle`.")
    h._send_json({"handle": handle, "repos": _portfolio_github_repos(handle, limit=int(payload.get("limit") or 20))})


def post_portfolio_import_github(h, payload) -> None:
    config = h._config()
    handle = str(payload.get("handle") or "").strip()
    names = payload.get("repos") if isinstance(payload.get("repos"), list) else []
    h._send_json(_portfolio_import_repos(config, [str(n) for n in names], handle=handle))


def post_portfolio_publish_guide(h, payload) -> None:
    h._send_json(_portfolio_publish_guide(h._config()))
