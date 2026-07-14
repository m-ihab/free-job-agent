"""CRUD for locally stored thumbs feedback snapshots."""

from __future__ import annotations

import json
from typing import Any

from job_agent.feedback import FeedbackRecord


class FeedbackMixin:
    def _connect(self) -> Any:
        raise NotImplementedError

    def save_feedback(self, feedback: FeedbackRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO job_feedback
                   (job_id, verdict, created_at, company, title_keywords_json, source)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(job_id) DO UPDATE SET
                     verdict=excluded.verdict,
                     created_at=excluded.created_at,
                     company=excluded.company,
                     title_keywords_json=excluded.title_keywords_json,
                     source=excluded.source""",
                (
                    feedback.job_id,
                    feedback.verdict,
                    feedback.created_at,
                    feedback.company,
                    json.dumps(feedback.title_keywords, ensure_ascii=False),
                    feedback.source,
                ),
            )

    def _row_to_feedback(self, row: Any) -> FeedbackRecord:
        return FeedbackRecord(
            job_id=str(row["job_id"]),
            verdict=str(row["verdict"]),  # type: ignore[arg-type]
            created_at=str(row["created_at"]),
            company=str(row["company"]),
            title_keywords=tuple(json.loads(row["title_keywords_json"])),
            source=str(row["source"]),
        )

    def get_feedback(self, job_id: str) -> FeedbackRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM job_feedback WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_feedback(row) if row else None

    def list_feedback(self) -> list[FeedbackRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM job_feedback ORDER BY created_at DESC, job_id"
            ).fetchall()
        return [self._row_to_feedback(row) for row in rows]

    def delete_feedback(self, job_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM job_feedback WHERE job_id = ?", (job_id,))
            return cursor.rowcount > 0
