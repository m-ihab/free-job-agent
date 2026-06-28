from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_agent.followup import draft_followup, list_due_followups, sync_followup_tasks
from job_agent.schemas.job import JobListing, JobStatus


def test_draft_followup_uses_only_known_job_facts():
    job = JobListing(title="Data Scientist Intern", company="Acme", status=JobStatus.MANUALLY_SUBMITTED)
    draft = draft_followup(job, contact_name="Sara")

    assert "Data Scientist Intern" in draft.subject
    assert "Acme" in draft.body
    assert "Sara" in draft.body
    assert "reference" not in draft.body.casefold()


def test_sync_and_list_due_followups(tmp_db):
    past = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    job = JobListing(title="Data Intern", company="Acme", status=JobStatus.MANUALLY_SUBMITTED, updated_at=past)
    tmp_db.save_job(job)
    job.updated_at = past

    created = sync_followup_tasks(tmp_db, [job])
    due = list_due_followups(tmp_db, [job], now=datetime.now(timezone.utc))

    assert created == 2
    assert due
    assert due[0].job_id == job.id
    assert due[0].kind == "week1"
