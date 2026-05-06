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
        """Save job and log intake event."""
        self.db.save_job(job)
        self.db.log_event(
            job.id,
            "JOB_ADDED",
            {"source": job.source, "title": job.title, "company": job.company},
        )
        return job

    def update_status(
        self, job_id: str, status: JobStatus, note: str = ""
    ) -> None:
        self.db.update_job_status(job_id, status)
        self.db.log_event(
            job_id,
            "STATUS_CHANGED",
            {"new_status": status.value, "note": note},
        )

    def save_packet(self, packet: ApplicationPacket) -> None:
        self.db.save_packet(packet)
        self.db.log_event(
            packet.job_id,
            "PACKET_SAVED",
            {"packet_id": packet.id, "version": packet.version},
            packet_id=packet.id,
        )

    def get_job(self, job_id: str) -> Optional[JobListing]:
        return self.db.get_job(job_id)

    def list_jobs(self, status: Optional[JobStatus] = None) -> list[JobListing]:
        return self.db.list_jobs(status=status)

    def get_history(self, job_id: str) -> list[dict]:
        return self.db.get_events(job_id)
