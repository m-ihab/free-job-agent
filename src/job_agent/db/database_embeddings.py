"""Embedding vector storage — a mixin composed into ``Database``.

Vectors live in the ``embeddings`` table keyed by ``(owner_id, kind)`` where
``kind`` is ``'job'`` or ``'profile'``. Stored as JSON text: local scale
(thousands of jobs) makes a vector index unnecessary. Assumes the host
provides ``self._connect()``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from job_agent.timeutil import utc_now

logger = logging.getLogger(__name__)


class EmbeddingsMixin:
    def _connect(self) -> Any:
        raise NotImplementedError

    def save_embedding(self, owner_id: str, kind: str, model: str, text_hash: str, vector: list[float]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO embeddings (owner_id, kind, model, text_hash, vector_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(owner_id, kind) DO UPDATE SET model=excluded.model, "
                "text_hash=excluded.text_hash, vector_json=excluded.vector_json, updated_at=excluded.updated_at",
                (owner_id, kind, model, text_hash, json.dumps(vector), utc_now()),
            )

    def get_embedding(self, owner_id: str, kind: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT model, text_hash, vector_json, updated_at FROM embeddings WHERE owner_id = ? AND kind = ?",
                (owner_id, kind),
            ).fetchone()
        if not row:
            return None
        try:
            vector = json.loads(row["vector_json"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt embedding JSON for %s/%s; ignoring cached row", owner_id, kind)
            return None
        if not isinstance(vector, list):
            return None
        return {
            "model": row["model"],
            "text_hash": row["text_hash"],
            "vector": vector,
            "updated_at": row["updated_at"],
        }

    def delete_embedding(self, owner_id: str, kind: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM embeddings WHERE owner_id = ? AND kind = ?", (owner_id, kind))

    def list_job_embeddings_for_company(self, company: str) -> list[dict]:
        """Return ``{owner_id, model, vector, title}`` rows for tracked jobs at one company."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT e.owner_id, e.model, e.vector_json, j.title FROM embeddings e "
                "JOIN jobs j ON j.id = e.owner_id "
                "WHERE e.kind = 'job' AND lower(trim(j.company)) = lower(trim(?))",
                (company,),
            ).fetchall()
        result: list[dict] = []
        for row in rows:
            try:
                vector = json.loads(row["vector_json"])
            except (json.JSONDecodeError, TypeError):
                logger.debug("Skipping corrupt embedding row in company scan")
                continue
            if isinstance(vector, list) and vector:
                result.append({
                    "owner_id": row["owner_id"],
                    "model": row["model"],
                    "vector": vector,
                    "title": row["title"] or "",
                })
        return result
