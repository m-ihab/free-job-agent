"""GET handler for local dashboard metrics."""
from __future__ import annotations

from typing import Any

from job_agent.analytics import compute_metrics
from job_agent.db.database import Database


def get_metrics(h: Any) -> None:
    db = Database(h._config().db_path)
    db.initialize()
    h._send_json(compute_metrics(db))
