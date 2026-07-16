"""GET handler for the local job-search knowledge graph."""
from __future__ import annotations

from typing import Any

from job_agent.db.database import Database
from job_agent.knowledge_graph import build_knowledge_graph


def get_graph(h: Any) -> None:
    db = Database(h._config().db_path)
    db.initialize()
    h._send_json(build_knowledge_graph(db))
