"""Application tracking helpers."""
from __future__ import annotations

from typing import Optional

from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket


class ApplicationTracker:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add_job(self, job: JobListing) -> JobListing:
        self.db.save_job(job)
        self.db.log_event(job.id, "JOB_ADDED", {"source": job.source, "title": job.title, "company": job.company})
        return job

    def update_status(self, job_id: str, status: JobStatus, note: str = "") -> None:
        job = self.db.resolve_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        changed = self.db.update_job_status(job.id, status)
        if not changed:
            raise ValueError(f"Job not found: {job_id}")
        self.db.log_event(job.id, "STATUS_CHANGED", {"new_status": status.value, "note": note})

    def delete_job(self, job_id: str, note: str = "") -> str:
        job = self.db.resolve_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        self.db.log_event(job.id, "JOB_REMOVED", {"title": job.title, "company": job.company, "note": note})
        self.db.delete_job(job.id)
        return job.id

    def save_packet(self, packet: ApplicationPacket) -> None:
        self.db.save_packet(packet)
        self.db.log_event(packet.job_id, "PACKET_SAVED", {"packet_id": packet.id, "version": packet.version}, packet_id=packet.id)

    def get_job(self, job_id: str) -> Optional[JobListing]:
        return self.db.resolve_job(job_id)

    def list_jobs(self, status: Optional[JobStatus] = None, limit: Optional[int] = 100) -> list[JobListing]:
        return self.db.list_jobs(status=status, limit=limit)

    def get_history(self, job_id: str) -> list[dict]:
        job = self.db.resolve_job(job_id)
        if not job:
            return []
        return self.db.get_events(job.id)

    def save_enrichment(self, job_id: str, payload: dict) -> None:
        self.db.save_enrichment(job_id, payload)

    def get_enrichment(self, job_id: str) -> Optional[dict]:
        job = self.db.resolve_job(job_id)
        if not job:
            return None
        return self.db.get_enrichment(job.id)
