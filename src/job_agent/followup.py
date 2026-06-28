"""Public follow-up phase API.

The conversion cockpit already owns persistence in ``conversion_followups``.
This module is the stable, user-facing seam for generators, CLI commands, and
future agents that need follow-up scheduling or grounded follow-up copy.
"""
from __future__ import annotations

from dataclasses import dataclass

from job_agent.conversion_followups import DueFollowup, list_due_followups, sync_followup_tasks
from job_agent.schemas.job import JobListing


@dataclass(frozen=True)
class FollowupDraft:
    job_id: str
    subject: str
    body: str
    safety_note: str

    def to_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


def draft_followup(job: JobListing, *, kind: str = "week1", contact_name: str | None = None) -> FollowupDraft:
    """Draft a short follow-up without inventing submission details.

    It uses only the job title/company already stored locally. Dates, recruiter
    names, application references, and interview promises are intentionally not
    synthesized here.
    """
    company = (job.company or "your team").strip()
    role = (job.title or "the role").strip()
    greeting = f"Hi {contact_name.strip()}," if contact_name and contact_name.strip() else "Hello,"
    cadence = "following up again" if kind == "week2" else "following up"
    subject = f"Follow-up on {role} application"
    body = "\n\n".join(
        [
            greeting,
            f"I hope you are well. I am {cadence} on my application for {role} at {company}.",
            "I remain interested in the opportunity and would be happy to share any additional information if useful.",
            "Best regards,",
        ]
    )
    return FollowupDraft(
        job_id=job.id,
        subject=subject,
        body=body,
        safety_note="Grounded in local job title/company only; add references or names manually if you have them.",
    )


__all__ = ["DueFollowup", "FollowupDraft", "draft_followup", "list_due_followups", "sync_followup_tasks"]
