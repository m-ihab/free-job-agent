"""SQLite database layer."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create all tables."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
                    job_type TEXT,
                    salary_min INTEGER,
                    salary_max INTEGER,
                    salary_currency TEXT NOT NULL DEFAULT 'USD',
                    description TEXT NOT NULL DEFAULT '',
                    requirements_json TEXT NOT NULL DEFAULT '[]',
                    responsibilities_json TEXT NOT NULL DEFAULT '[]',
                    tech_stack_json TEXT NOT NULL DEFAULT '[]',
                    benefits_json TEXT NOT NULL DEFAULT '[]',
                    apply_url TEXT,
                    posted_date TEXT,
                    deadline TEXT,
                    status TEXT NOT NULL DEFAULT 'NEW',
                    fit_score REAL,
                    fit_notes_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS packets (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'DRAFT',
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
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    packet_id TEXT,
                    event_type TEXT NOT NULL,
                    event_data_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
            """)

    # ---- Job methods ----

    def save_job(self, job: JobListing) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO jobs VALUES (
                    :id, :fingerprint, :source, :source_url, :raw_text,
                    :title, :company, :location, :remote, :job_type,
                    :salary_min, :salary_max, :salary_currency,
                    :description, :requirements_json, :responsibilities_json,
                    :tech_stack_json, :benefits_json, :apply_url,
                    :posted_date, :deadline, :status, :fit_score,
                    :fit_notes_json, :created_at, :updated_at
                )""",
                {
                    "id": job.id,
                    "fingerprint": job.fingerprint,
                    "source": job.source,
                    "source_url": job.source_url,
                    "raw_text": job.raw_text,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "remote": int(job.remote),
                    "job_type": job.job_type,
                    "salary_min": job.salary_min,
                    "salary_max": job.salary_max,
                    "salary_currency": job.salary_currency,
                    "description": job.description,
                    "requirements_json": json.dumps(job.requirements),
                    "responsibilities_json": json.dumps(job.responsibilities),
                    "tech_stack_json": json.dumps(job.tech_stack),
                    "benefits_json": json.dumps(job.benefits),
                    "apply_url": job.apply_url,
                    "posted_date": job.posted_date,
                    "deadline": job.deadline,
                    "status": job.status.value,
                    "fit_score": job.fit_score,
                    "fit_notes_json": json.dumps(job.fit_notes),
                    "created_at": job.created_at,
                    "updated_at": job.updated_at,
                },
            )

    def _row_to_job(self, row: sqlite3.Row) -> JobListing:
        d = dict(row)
        d["remote"] = bool(d["remote"])
        d["requirements"] = json.loads(d.pop("requirements_json"))
        d["responsibilities"] = json.loads(d.pop("responsibilities_json"))
        d["tech_stack"] = json.loads(d.pop("tech_stack_json"))
        d["benefits"] = json.loads(d.pop("benefits_json"))
        d["fit_notes"] = json.loads(d.pop("fit_notes_json"))
        return JobListing(**d)

    def get_job(self, job_id: str) -> Optional[JobListing]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def get_job_by_fingerprint(self, fingerprint: str) -> Optional[JobListing]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, status: Optional[JobStatus] = None, limit: int = 100) -> list[JobListing]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status.value, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def update_job_status(self, job_id: str, status: JobStatus) -> None:
        import datetime
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, datetime.datetime.now(datetime.timezone.utc).isoformat(), job_id),
            )

    def delete_job(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    # ---- Packet methods ----

    def save_packet(self, packet: ApplicationPacket) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO packets VALUES (
                    :id, :job_id, :version, :status,
                    :tailored_cv_md, :tailored_cv_html, :tailored_cv_pdf_path,
                    :cover_letter_md, :cover_letter_html, :cover_letter_pdf_path,
                    :qa_answers_json, :assistant_page_html, :notes,
                    :created_at, :updated_at
                )""",
                {
                    "id": packet.id,
                    "job_id": packet.job_id,
                    "version": packet.version,
                    "status": packet.status.value,
                    "tailored_cv_md": packet.tailored_cv_md,
                    "tailored_cv_html": packet.tailored_cv_html,
                    "tailored_cv_pdf_path": packet.tailored_cv_pdf_path,
                    "cover_letter_md": packet.cover_letter_md,
                    "cover_letter_html": packet.cover_letter_html,
                    "cover_letter_pdf_path": packet.cover_letter_pdf_path,
                    "qa_answers_json": json.dumps(packet.qa_answers),
                    "assistant_page_html": packet.assistant_page_html,
                    "notes": packet.notes,
                    "created_at": packet.created_at,
                    "updated_at": packet.updated_at,
                },
            )

    def _row_to_packet(self, row: sqlite3.Row) -> ApplicationPacket:
        d = dict(row)
        d["qa_answers"] = json.loads(d.pop("qa_answers_json"))
        return ApplicationPacket(**d)

    def get_packet(self, packet_id: str) -> Optional[ApplicationPacket]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM packets WHERE id = ?", (packet_id,)
            ).fetchone()
        return self._row_to_packet(row) if row else None

    def get_packets_for_job(self, job_id: str) -> list[ApplicationPacket]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM packets WHERE job_id = ? ORDER BY version DESC",
                (job_id,),
            ).fetchall()
        return [self._row_to_packet(r) for r in rows]

    # ---- Event methods ----

    def log_event(
        self,
        job_id: str,
        event_type: str,
        event_data: dict,
        packet_id: Optional[str] = None,
    ) -> None:
        import datetime
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO events (job_id, packet_id, event_type, event_data_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    job_id,
                    packet_id,
                    event_type,
                    json.dumps(event_data),
                    datetime.datetime.now(datetime.timezone.utc).isoformat(),
                ),
            )

    def get_events(self, job_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE job_id = ? ORDER BY id ASC", (job_id,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["event_data"] = json.loads(d.pop("event_data_json"))
            result.append(d)
        return result
