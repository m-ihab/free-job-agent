"""Career-page discovery API routes (ATS slug probing, local board registry)."""
from __future__ import annotations

import logging

from job_agent.db.database import Database
from job_agent.intake import discovery

logger = logging.getLogger(__name__)

_MAX_COMPANIES_PER_REQUEST = 10


def _db(h) -> Database:
    config = h._config()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    return db


def get_company_boards(h) -> None:
    h._send_json({"boards": _db(h).list_company_boards()})


def post_discover_boards(h, payload: dict) -> None:
    """Probe public ATS APIs for the given companies (capped per request)."""
    raw = payload.get("companies") or []
    if isinstance(raw, str):
        raw = [part for chunk in raw.splitlines() for part in chunk.split(",")]
    companies = [str(c).strip() for c in raw if str(c).strip()]
    if not companies:
        companies = discovery.default_target_companies()
    if len(companies) > _MAX_COMPANIES_PER_REQUEST:
        companies = companies[:_MAX_COMPANIES_PER_REQUEST]
    summary = discovery.discover_boards(_db(h), companies)
    h._send_json(summary)
