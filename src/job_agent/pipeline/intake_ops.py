"""Intake + scoring stage of the pipeline (split from pipeline.py, R1 2026-07-09)."""
from __future__ import annotations

import logging
from pathlib import Path

from job_agent import embeddings
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.fingerprint import set_fingerprint
from job_agent.intake.file import ingest_file
from job_agent.intake.paste import ingest_paste
from job_agent.intake.url import ingest_url
from job_agent.normalizer import normalize
from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.scorer import score_job
from job_agent.tracker import ApplicationTracker

logger = logging.getLogger(__name__)


def _tracker(config: AppConfig) -> ApplicationTracker:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    return ApplicationTracker(db)


def _semantic_duplicate(tracker: ApplicationTracker, job: JobListing) -> JobListing | None:
    """Fail-soft near-duplicate lookup via local embeddings. Never raises."""
    try:
        dupe_id = embeddings.find_near_duplicate(tracker.db, job)
        if dupe_id:
            existing = tracker.db.get_job(dupe_id)
            if existing:
                logger.info(
                    "Semantic near-duplicate: '%s' @ %s matches tracked job %s",
                    job.title, job.company, dupe_id,
                )
                # The deduped job is never inserted; drop its cached vector so
                # the embeddings table doesn't accumulate orphan rows.
                tracker.db.delete_embedding(job.id, "job")
                return existing
    except Exception:
        logger.debug("Semantic duplicate check skipped", exc_info=True)
    return None


def add_job_to_tracker(config: AppConfig, job: JobListing) -> tuple[JobListing, bool]:
    tracker = _tracker(config)
    job = normalize(job)
    job = set_fingerprint(job)
    existing = tracker.db.get_job_by_fingerprint(job.fingerprint) if job.fingerprint else None
    if existing:
        return existing, False
    existing = _semantic_duplicate(tracker, job)
    if existing:
        return existing, False
    tracker.add_job(job)
    return job, True


def add_file_job(config: AppConfig, path: Path | str, title: str | None = None, company: str | None = None, url: str | None = None) -> tuple[JobListing, bool]:
    return add_job_to_tracker(config, ingest_file(path, title=title, company=company, url=url))


def add_text_job(config: AppConfig, text: str, title: str | None = None, company: str | None = None, url: str | None = None) -> tuple[JobListing, bool]:
    return add_job_to_tracker(config, ingest_paste(text, title=title, company=company, url=url))


def add_url_job(config: AppConfig, url: str) -> tuple[JobListing, bool]:
    return add_job_to_tracker(config, ingest_url(url))


def score_and_save(config: AppConfig, job: JobListing, profile: CandidateProfile) -> JobListing:
    tracker = _tracker(config)
    try:
        semantic = embeddings.semantic_similarity(job, profile, tracker.db)
    except Exception:
        logger.debug("Semantic similarity skipped", exc_info=True)
        semantic = None
    breakdown = score_job(job, profile, semantic_score=semantic)
    job.fit_score = breakdown.total_score
    job.fit_confidence = breakdown.confidence
    job.fit_decision = breakdown.decision
    job.fit_notes = breakdown.notes
    job.missing_requirements = breakdown.missing_requirements
    job.risk_flags = sorted(set(job.risk_flags + breakdown.risk_flags))
    tracker.db.save_job(job)
    tracker.update_status(job.id, JobStatus.SCORED)
    return job
