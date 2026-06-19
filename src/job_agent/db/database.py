"""SQLite database layer."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket
from job_agent.timeutil import utc_now

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create all tables and indexes."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_url TEXT,
                    raw_text TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT,
                    remote INTEGER NOT NULL DEFAULT 0,
                    work_mode TEXT,
                    seniority TEXT,
                    job_type TEXT,
                    salary_min INTEGER,
                    salary_max INTEGER,
                    salary_currency TEXT NOT NULL DEFAULT 'USD',
                    description TEXT NOT NULL DEFAULT '',
                    requirements_json TEXT NOT NULL DEFAULT '[]',
                    responsibilities_json TEXT NOT NULL DEFAULT '[]',
                    tech_stack_json TEXT NOT NULL DEFAULT '[]',
                    benefits_json TEXT NOT NULL DEFAULT '[]',
                    languages_json TEXT NOT NULL DEFAULT '[]',
                    risk_flags_json TEXT NOT NULL DEFAULT '[]',
                    apply_url TEXT,
                    posted_date TEXT,
                    deadline TEXT,
                    status TEXT NOT NULL DEFAULT 'NEW',
                    fit_score REAL,
                    fit_confidence REAL,
                    fit_decision TEXT,
                    fit_notes_json TEXT NOT NULL DEFAULT '[]',
                    missing_requirements_json TEXT NOT NULL DEFAULT '[]',
                    recruiter_name TEXT,
                    recruiter_email TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_fingerprint_unique
                    ON jobs(fingerprint) WHERE fingerprint != '';
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

                CREATE TABLE IF NOT EXISTS packets (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    job_fingerprint TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'DRAFT',
                    fit_score REAL,
                    fit_confidence REAL,
                    fit_decision TEXT,
                    fit_notes_json TEXT NOT NULL DEFAULT '[]',
                    risk_flags_json TEXT NOT NULL DEFAULT '[]',
                    profile_hash TEXT,
                    master_cv_hash TEXT,
                    qa_profile_hash TEXT,
                    artifacts_json TEXT NOT NULL DEFAULT '[]',
                    screening_answers_json TEXT NOT NULL DEFAULT '[]',
                    tailored_cv_md TEXT NOT NULL DEFAULT '',
                    tailored_cv_html TEXT NOT NULL DEFAULT '',
                    tailored_cv_pdf_path TEXT,
                    cover_letter_md TEXT NOT NULL DEFAULT '',
                    cover_letter_html TEXT NOT NULL DEFAULT '',
                    cover_letter_pdf_path TEXT,
                    qa_answers_json TEXT NOT NULL DEFAULT '{}',
                    assistant_page_html TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_packets_job_id ON packets(job_id);
                CREATE INDEX IF NOT EXISTS idx_packets_status ON packets(status);

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    packet_id TEXT,
                    event_type TEXT NOT NULL,
                    event_data_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                    FOREIGN KEY(packet_id) REFERENCES packets(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS enrichments (
                    job_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS ai_cache (
                    job_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    model TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, kind),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_ai_cache_kind ON ai_cache(kind);

                -- Additive migrations — safe to re-run on existing databases.
                -- SQLite ignores "duplicate column" errors only via try/catch below.

                -- Sources (ATS slugs etc.) that have recently 404'd. The
                -- autopilot consults this to skip dead boards without nagging
                -- the user. Auto-expires after broken_until passes.
                CREATE TABLE IF NOT EXISTS broken_sources (
                    source TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    status_code INTEGER,
                    reason TEXT NOT NULL DEFAULT '',
                    broken_at TEXT NOT NULL,
                    broken_until TEXT NOT NULL,
                    PRIMARY KEY (source, slug)
                );
            """)
            # Additive column migrations — run after CREATE TABLE so new DBs
            # get the column inline and existing DBs get it here.
            for _migration in [
                "ALTER TABLE jobs ADD COLUMN recruiter_name TEXT",
                "ALTER TABLE jobs ADD COLUMN recruiter_email TEXT",
            ]:
                try:
                    conn.execute(_migration)
                except sqlite3.OperationalError:
                    logger.debug("Migration skipped (column already exists): %s", _migration)

    # ---- Job methods ----

    def save_job(self, job: JobListing) -> None:
        job.updated_at = utc_now()
        values = {
            "id": job.id,
            "fingerprint": job.fingerprint,
            "source": job.source,
            "source_url": job.source_url,
            "raw_text": job.raw_text,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "remote": int(job.remote),
            "work_mode": job.work_mode,
            "seniority": job.seniority,
            "job_type": job.job_type,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "salary_currency": job.salary_currency,
            "description": job.description,
            "requirements_json": json.dumps(job.requirements, ensure_ascii=False),
            "responsibilities_json": json.dumps(job.responsibilities, ensure_ascii=False),
            "tech_stack_json": json.dumps(job.tech_stack, ensure_ascii=False),
            "benefits_json": json.dumps(job.benefits, ensure_ascii=False),
            "languages_json": json.dumps(job.languages, ensure_ascii=False),
            "risk_flags_json": json.dumps(job.risk_flags, ensure_ascii=False),
            "apply_url": job.apply_url,
            "posted_date": job.posted_date,
            "deadline": job.deadline,
            "status": job.status.value,
            "fit_score": job.fit_score,
            "fit_confidence": job.fit_confidence,
            "fit_decision": job.fit_decision,
            "fit_notes_json": json.dumps(job.fit_notes, ensure_ascii=False),
            "missing_requirements_json": json.dumps(job.missing_requirements, ensure_ascii=False),
            "recruiter_name": job.recruiter_name,
            "recruiter_email": job.recruiter_email,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }
        columns = ", ".join(values.keys())
        placeholders = ", ".join(f":{k}" for k in values)
        updates = ", ".join(f"{k}=excluded.{k}" for k in values if k != "id")
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO jobs ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                values,
            )

    def _row_to_job(self, row: sqlite3.Row) -> JobListing:
        d = dict(row)
        d["remote"] = bool(d["remote"])
        d["requirements"] = json.loads(d.pop("requirements_json"))
        d["responsibilities"] = json.loads(d.pop("responsibilities_json"))
        d["tech_stack"] = json.loads(d.pop("tech_stack_json"))
        d["benefits"] = json.loads(d.pop("benefits_json"))
        d["languages"] = json.loads(d.pop("languages_json", "[]"))
        d["risk_flags"] = json.loads(d.pop("risk_flags_json", "[]"))
        d["fit_notes"] = json.loads(d.pop("fit_notes_json"))
        d["missing_requirements"] = json.loads(d.pop("missing_requirements_json", "[]"))
        d.setdefault("recruiter_name", None)
        d.setdefault("recruiter_email", None)
        return JobListing(**d)

    def get_job(self, job_id: str) -> Optional[JobListing]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def get_job_by_prefix(self, prefix: str) -> Optional[JobListing]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE id LIKE ? ORDER BY created_at DESC LIMIT 2", (prefix + "%",)).fetchall()
        if len(rows) == 1:
            return self._row_to_job(rows[0])
        return None

    def resolve_job(self, job_id_or_prefix: str) -> Optional[JobListing]:
        return self.get_job(job_id_or_prefix) or self.get_job_by_prefix(job_id_or_prefix)

    def get_job_by_fingerprint(self, fingerprint: str) -> Optional[JobListing]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE fingerprint = ?", (fingerprint,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, status: Optional[JobStatus] = None, limit: Optional[int] = 100) -> list[JobListing]:
        with self._connect() as conn:
            if status:
                if limit is None:
                    rows = conn.execute("SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", (status.value,)).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status.value, limit)).fetchall()
            else:
                if limit is None:
                    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
                else:
                    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_job(r) for r in rows]

    def get_needs_manual(self, limit: Optional[int] = 100) -> list[JobListing]:
        """Jobs the full-auto run handed off (hit a CAPTCHA/login/anti-bot wall);
        their prepared packets are ready for the user to submit by hand."""
        return self.list_jobs(status=JobStatus.NEEDS_MANUAL, limit=limit)

    def list_jobs_without_packets(self, min_score: Optional[float] = None, limit: int = 20) -> list[JobListing]:
        """Return jobs that have no associated packets yet, skipping terminal statuses."""
        _terminal = ("FILTERED", "DUPLICATE", "WITHDRAWN", "REJECTED", "APPLYING", "APPLIED", "MANUALLY_SUBMITTED")
        placeholders = ",".join("?" * len(_terminal))
        with self._connect() as conn:
            if min_score is not None:
                rows = conn.execute(
                    f"SELECT * FROM jobs WHERE id NOT IN (SELECT DISTINCT job_id FROM packets) "
                    f"AND status NOT IN ({placeholders}) "
                    f"AND (fit_score IS NULL OR fit_score >= ?) "
                    f"ORDER BY fit_score DESC, created_at DESC LIMIT ?",
                    (*_terminal, min_score, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM jobs WHERE id NOT IN (SELECT DISTINCT job_id FROM packets) "
                    f"AND status NOT IN ({placeholders}) "
                    f"ORDER BY fit_score DESC, created_at DESC LIMIT ?",
                    (*_terminal, limit),
                ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def update_job_status(self, job_id: str, status: JobStatus) -> bool:
        with self._connect() as conn:
            cur = conn.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", (status.value, utc_now(), job_id))
            return cur.rowcount > 0

    def delete_job(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    # ---- Packet methods ----

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

    # ---- Event methods ----

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

    # ---- Enrichment methods ----

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
