"""Packet-row CRUD for the database, as a mixin composed into ``Database``.

Assumes the host class provides ``self._connect()``.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from job_agent.schemas.packet import ApplicationPacket
from job_agent.timeutil import utc_now


class PacketsMixin:
    def save_packet(self, packet: ApplicationPacket) -> None:
        packet.updated_at = utc_now()
        values = {
            "id": packet.id,
            "job_id": packet.job_id,
            "job_fingerprint": packet.job_fingerprint,
            "version": packet.version,
            "status": packet.status.value,
            "fit_score": packet.fit_score,
            "fit_confidence": packet.fit_confidence,
            "fit_decision": packet.fit_decision,
            "fit_notes_json": json.dumps(packet.fit_notes, ensure_ascii=False),
            "risk_flags_json": json.dumps(packet.risk_flags, ensure_ascii=False),
            "profile_hash": packet.profile_hash,
            "master_cv_hash": packet.master_cv_hash,
            "qa_profile_hash": packet.qa_profile_hash,
            "artifacts_json": json.dumps([a.dict() for a in packet.artifacts], ensure_ascii=False),
            "screening_answers_json": json.dumps([a.dict() for a in packet.screening_answers], ensure_ascii=False),
            "tailored_cv_md": packet.tailored_cv_md,
            "tailored_cv_html": packet.tailored_cv_html,
            "tailored_cv_pdf_path": packet.tailored_cv_pdf_path,
            "cover_letter_md": packet.cover_letter_md,
            "cover_letter_html": packet.cover_letter_html,
            "cover_letter_pdf_path": packet.cover_letter_pdf_path,
            "qa_answers_json": json.dumps(packet.qa_answers, ensure_ascii=False),
            "assistant_page_html": packet.assistant_page_html,
            "notes": packet.notes,
            "created_at": packet.created_at,
            "updated_at": packet.updated_at,
        }
        columns = ", ".join(values.keys())
        placeholders = ", ".join(f":{k}" for k in values)
        updates = ", ".join(f"{k}=excluded.{k}" for k in values if k != "id")
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO packets ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                values,
            )

    def _row_to_packet(self, row: sqlite3.Row) -> ApplicationPacket:
        d = dict(row)
        d["fit_notes"] = json.loads(d.pop("fit_notes_json", "[]"))
        d["risk_flags"] = json.loads(d.pop("risk_flags_json", "[]"))
        d["artifacts"] = json.loads(d.pop("artifacts_json", "[]"))
        d["screening_answers"] = json.loads(d.pop("screening_answers_json", "[]"))
        d["qa_answers"] = json.loads(d.pop("qa_answers_json"))
        return ApplicationPacket(**d)

    def get_packet(self, packet_id: str) -> Optional[ApplicationPacket]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM packets WHERE id = ?", (packet_id,)).fetchone()
        return self._row_to_packet(row) if row else None

    def get_packet_by_prefix(self, prefix: str) -> Optional[ApplicationPacket]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM packets WHERE id LIKE ? ORDER BY created_at DESC LIMIT 2", (prefix + "%",)).fetchall()
        if len(rows) == 1:
            return self._row_to_packet(rows[0])
        return None

    def resolve_packet(self, packet_id_or_prefix: str) -> Optional[ApplicationPacket]:
        return self.get_packet(packet_id_or_prefix) or self.get_packet_by_prefix(packet_id_or_prefix)

    def get_packets_for_job(self, job_id: str) -> list[ApplicationPacket]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM packets WHERE job_id = ? ORDER BY version DESC, created_at DESC", (job_id,)).fetchall()
        return [self._row_to_packet(r) for r in rows]

    def list_packets(self, limit: int = 100) -> list[ApplicationPacket]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM packets ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_packet(r) for r in rows]

    def bulk_latest_packets(self, job_ids: list[str]) -> dict[str, ApplicationPacket]:
        """Return the newest packet per job for the given list."""
        if not job_ids:
            return {}
        placeholders = ",".join("?" * len(job_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM packets WHERE job_id IN ({placeholders}) ORDER BY version DESC, created_at DESC",
                tuple(job_ids),
            ).fetchall()
        latest: dict[str, ApplicationPacket] = {}
        for row in rows:
            packet = self._row_to_packet(row)
            if packet.job_id not in latest:
                latest[packet.job_id] = packet
        return latest
