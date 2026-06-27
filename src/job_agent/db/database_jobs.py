"""Job-row CRUD for the database, as a mixin composed into ``Database``.

The mixin assumes the host class provides ``self._connect()`` (a context manager
yielding a sqlite3 connection) — :class:`job_agent.db.database.Database` does.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from job_agent.schemas.job import JobListing, JobStatus
from job_agent.timeutil import utc_now


class JobsMixin:
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
