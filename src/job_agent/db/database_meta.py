"""Events, enrichment, AI cache, bulk reads, and broken-source tracking — a
mixin composed into ``Database``. Assumes the host provides ``self._connect()``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from job_agent.timeutil import utc_now

logger = logging.getLogger(__name__)


class MetaMixin:
    def _connect(self) -> Any:
        raise NotImplementedError

    # ---- Events ----

    def log_event(self, job_id: Optional[str], event_type: str, event_data: dict, packet_id: Optional[str] = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events (job_id, packet_id, event_type, event_data_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (job_id, packet_id, event_type, json.dumps(event_data, ensure_ascii=False), utc_now()),
            )

    def get_events(self, job_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM events WHERE job_id = ? ORDER BY id ASC", (job_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["event_data"] = json.loads(d.pop("event_data_json"))
            result.append(d)
        return result

    # ---- Enrichment ----

    def save_enrichment(self, job_id: str, payload: dict) -> None:
        values = {
            "job_id": job_id,
            "payload_json": json.dumps(payload, ensure_ascii=False),
            "updated_at": utc_now(),
        }
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO enrichments (job_id, payload_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (values["job_id"], values["payload_json"], values["updated_at"]),
            )

    def get_enrichment(self, job_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json, updated_at FROM enrichments WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt enrichment JSON for job %s; ignoring cached row", job_id)
            return None
        payload["updated_at"] = row["updated_at"]
        return payload

    # ---- AI cache ----

    def save_ai_cache(self, job_id: str, kind: str, payload: dict, model: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ai_cache (job_id, kind, payload_json, model, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id, kind) DO UPDATE SET payload_json=excluded.payload_json, model=excluded.model, updated_at=excluded.updated_at",
                (job_id, kind, json.dumps(payload, ensure_ascii=False), model, utc_now()),
            )

    def get_ai_cache(self, job_id: str, kind: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, model, updated_at FROM ai_cache WHERE job_id = ? AND kind = ?",
                (job_id, kind),
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt AI-cache JSON for job %s kind %s; ignoring", job_id, kind)
            return None
        if isinstance(payload, dict):
            payload["model"] = row["model"]
            payload["updated_at"] = row["updated_at"]
        return payload

    def list_ai_cache_for_job(self, job_id: str) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, payload_json, model, updated_at FROM ai_cache WHERE job_id = ?",
                (job_id,),
            ).fetchall()
        result: dict[str, dict] = {}
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (json.JSONDecodeError, TypeError):
                logger.debug("Skipping corrupt cached JSON row in bulk read")
                continue
            if isinstance(payload, dict):
                payload["model"] = row["model"]
                payload["updated_at"] = row["updated_at"]
                result[row["kind"]] = payload
        return result

    # ---- Bulk reads used by the dashboard's jobs list to avoid N+1 queries ----

    def bulk_get_enrichments(self, job_ids: list[str]) -> dict[str, dict]:
        """Return ``{job_id: enrichment_payload}`` for the given jobs."""
        if not job_ids:
            return {}
        placeholders = ",".join("?" * len(job_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT job_id, payload_json, updated_at FROM enrichments WHERE job_id IN ({placeholders})",
                tuple(job_ids),
            ).fetchall()
        result: dict[str, dict] = {}
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (json.JSONDecodeError, TypeError):
                logger.debug("Skipping corrupt cached JSON row in bulk read")
                continue
            if isinstance(payload, dict):
                payload["updated_at"] = row["updated_at"]
                result[row["job_id"]] = payload
        return result

    def bulk_list_ai_cache(self, job_ids: list[str]) -> dict[str, dict[str, dict]]:
        """Return ``{job_id: {kind: payload}}`` for the given jobs."""
        if not job_ids:
            return {}
        placeholders = ",".join("?" * len(job_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT job_id, kind, payload_json, model, updated_at FROM ai_cache WHERE job_id IN ({placeholders})",
                tuple(job_ids),
            ).fetchall()
        result: dict[str, dict[str, dict]] = {}
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (json.JSONDecodeError, TypeError):
                logger.debug("Skipping corrupt cached JSON row in bulk read")
                continue
            if isinstance(payload, dict):
                payload["model"] = row["model"]
                payload["updated_at"] = row["updated_at"]
                result.setdefault(row["job_id"], {})[row["kind"]] = payload
        return result

    # ---- Broken sources (ATS slugs that 404'd) ----

    def mark_source_broken(self, source: str, slug: str, *, status_code: int = 0, reason: str = "", hours: float = 24.0) -> None:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        until = now + timedelta(hours=hours)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO broken_sources (source, slug, status_code, reason, broken_at, broken_until) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source, slug) DO UPDATE SET status_code=excluded.status_code, "
                "reason=excluded.reason, broken_at=excluded.broken_at, broken_until=excluded.broken_until",
                (source, slug, int(status_code or 0), reason, now.isoformat(), until.isoformat()),
            )

    def clear_broken_source(self, source: str, slug: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM broken_sources WHERE source=? AND slug=?", (source, slug))

    def is_source_broken(self, source: str, slug: str) -> bool:
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT broken_until FROM broken_sources WHERE source=? AND slug=? AND broken_until > ?",
                (source, slug, now_iso),
            ).fetchone()
        return bool(row)

    def list_broken_sources(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source, slug, status_code, reason, broken_at, broken_until FROM broken_sources "
                "ORDER BY broken_until DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- Evidence items ----

    def replace_evidence_items(self, items: list[dict]) -> None:
        """Replace derived evidence rows with a fresh local rebuild."""
        with self._connect() as conn:
            conn.execute("DELETE FROM evidence_items")
            conn.executemany(
                "INSERT INTO evidence_items "
                "(kind, label, value, source, source_ref, confidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item["kind"],
                        item["label"],
                        item.get("value", ""),
                        item["source"],
                        item.get("source_ref"),
                        float(item.get("confidence", 1.0)),
                        utc_now(),
                    )
                    for item in items
                ],
            )

    def list_evidence_items(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, label, value, source, source_ref, confidence "
                "FROM evidence_items ORDER BY kind, label, source_ref"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_evidence_items_with_ids(self) -> list[dict]:
        """Return evidence rows with their concrete store identifiers."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, kind, label, value, source, source_ref, confidence "
                "FROM evidence_items ORDER BY kind, label, source_ref"
            ).fetchall()
        return [dict(row) for row in rows]
