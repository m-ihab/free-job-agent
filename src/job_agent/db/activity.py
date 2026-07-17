"""Read-only access to the global tracker event log."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def list_activity_events(db_path: Path) -> list[dict[str, Any]]:
    """Return every stored event newest-first, including jobless system rows."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        rows = conn.execute(
            "SELECT events.*, jobs.title AS job_title, jobs.company AS job_company "
            "FROM events LEFT JOIN jobs ON jobs.id = events.job_id "
            "ORDER BY events.id DESC"
        ).fetchall()
    finally:
        conn.close()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        raw = item.pop("event_data_json", "{}")
        try:
            item["event_data"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt event JSON for activity row %s", item.get("id"))
            item["event_data"] = {}
        result.append(item)
    return result
