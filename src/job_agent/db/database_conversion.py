"""Conversion-OS persistence helpers for follow-up tasks."""
from __future__ import annotations

from typing import Any

from job_agent.timeutil import utc_now


class ConversionMixin:
    def _connect(self) -> Any:
        raise NotImplementedError

    def upsert_followup_task(self, job_id: str, kind: str, due_at: str, status: str = "due") -> int:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO followup_tasks (job_id, kind, due_at, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id, kind, due_at) DO UPDATE SET "
                "status=excluded.status, updated_at=excluded.updated_at",
                (job_id, kind, due_at, status, now, now),
            )
            row = conn.execute(
                "SELECT id FROM followup_tasks WHERE job_id=? AND kind=? AND due_at=?",
                (job_id, kind, due_at),
            ).fetchone()
        return int(row["id"])

    def list_followup_tasks(
        self,
        *,
        status: str | None = None,
        due_before: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[object] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if due_before:
            clauses.append("due_at <= ?")
            params.append(due_before)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, job_id, kind, due_at, status, created_at, updated_at "
                f"FROM followup_tasks {where} ORDER BY due_at ASC, id ASC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_followup_task(self, task_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE followup_tasks SET status='done', updated_at=? WHERE id=?",
                (utc_now(), int(task_id)),
            )
            return cur.rowcount > 0
