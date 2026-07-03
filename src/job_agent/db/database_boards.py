"""Discovered company ATS boards — a mixin composed into ``Database``.

One row per verified (source, slug); discovery upserts so re-runs refresh
``verified_at`` instead of duplicating. Assumes the host provides
``self._connect()``.
"""
from __future__ import annotations

from typing import Any, Optional

from job_agent.timeutil import utc_now


class BoardsMixin:
    def _connect(self) -> Any:
        raise NotImplementedError

    def save_company_board(self, company: str, source: str, slug: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO company_boards (company, source, slug, verified_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(source, slug) DO UPDATE SET company=excluded.company, "
                "verified_at=excluded.verified_at",
                (company, source, slug, utc_now()),
            )

    def list_company_boards(self, source: Optional[str] = None) -> list[dict]:
        query = "SELECT company, source, slug, verified_at FROM company_boards"
        params: tuple = ()
        if source:
            query += " WHERE source = ?"
            params = (source,)
        query += " ORDER BY company COLLATE NOCASE, source"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def delete_company_board(self, source: str, slug: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM company_boards WHERE source = ? AND slug = ?", (source, slug))
