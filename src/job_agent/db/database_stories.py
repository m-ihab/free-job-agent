"""Interview story bank storage — a mixin composed into ``Database``.

Assumes the host provides ``self._connect()``. ``skills`` round-trips as a
JSON list on the ``skills_json`` column.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from job_agent.timeutil import utc_now

logger = logging.getLogger(__name__)

_STORY_TEXT_FIELDS = ("title", "situation", "task", "action", "result", "reflection", "source")


def _row_to_story(row: Any) -> Optional[dict]:
    try:
        skills = json.loads(row["skills_json"])
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupt skills JSON for story %s; using empty list", row["id"])
        skills = []
    story = {"id": row["id"], "skills": skills if isinstance(skills, list) else []}
    for fieldname in _STORY_TEXT_FIELDS:
        story[fieldname] = row[fieldname]
    story["created_at"] = row["created_at"]
    story["updated_at"] = row["updated_at"]
    return story


class StoriesMixin:
    def _connect(self) -> Any:
        raise NotImplementedError

    def save_story(self, story: dict) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO stories (id, title, skills_json, situation, task, action, result, "
                "reflection, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title, skills_json=excluded.skills_json, "
                "situation=excluded.situation, task=excluded.task, action=excluded.action, "
                "result=excluded.result, reflection=excluded.reflection, source=excluded.source, "
                "updated_at=excluded.updated_at",
                (
                    story["id"],
                    story.get("title", ""),
                    json.dumps(story.get("skills") or [], ensure_ascii=False),
                    story.get("situation", ""),
                    story.get("task", ""),
                    story.get("action", ""),
                    story.get("result", ""),
                    story.get("reflection", ""),
                    story.get("source", "manual"),
                    now,
                    now,
                ),
            )

    def get_story(self, story_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
        return _row_to_story(row) if row else None

    def list_stories(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM stories ORDER BY title COLLATE NOCASE").fetchall()
        return [story for story in (_row_to_story(row) for row in rows) if story]

    def delete_story(self, story_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM stories WHERE id = ?", (story_id,))
