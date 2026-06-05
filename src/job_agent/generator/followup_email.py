"""Generate follow-up emails for three stages of the application lifecycle.

Type 1 — 5-7 days after applying: gentle nudge, confirm receipt
Type 2 — 14 days: second follow-up if no response
Type 3 — After rejection: graceful exit that keeps the door open
"""
from __future__ import annotations

from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.schemas.job import JobListing


def _first_name(full_name: str) -> str:
    return full_name.strip().split()[0] if full_name.strip() else ""


def generate_followup_email(
    job: JobListing,
    master_cv: MasterCV,
    profile: CandidateProfile,
    follow_type: str = "week1",
    recruiter_name: str | None = None,
) -> str:
    """Return a follow-up email draft as Markdown.

    follow_type: 'week1' | 'week2' | 'rejection'
    """
    contact = profile.contact
    full_name = contact.name if contact else ""
    candidate_first = _first_name(full_name)
    recruiter = recruiter_name or job.recruiter_name or ""
    greeting = f"Dear {recruiter}," if recruiter else "Dear Hiring Team,"
    role = job.title or "the position"
    company = job.company or "your company"

    signature_parts = [full_name]
    if contact and contact.email:
        signature_parts.append(contact.email)
    if contact and hasattr(contact, "phone") and contact.phone:
        signature_parts.append(contact.phone)
    if contact and hasattr(contact, "linkedin_url") and contact.linkedin_url:
        signature_parts.append(contact.linkedin_url)
    signature = " | ".join(p for p in signature_parts if p)

    if follow_type == "week1":
        subject = f"Following up — {role} application"
        body_lines = [
            greeting,
            "",
            f"I applied for the {role} role at {company} about a week ago and wanted to follow up briefly.",
            "I remain very enthusiastic about the opportunity and would love the chance to discuss how my background fits your team's needs.",
            "",
            "Please let me know if you need any additional materials — happy to provide references, portfolio links, or a brief call whenever convenient.",
            "",
            "Looking forward to hearing from you.",
            "",
            "Best regards,",
            signature,
        ]

    elif follow_type == "week2":
        subject = f"Second follow-up — {role} at {company}"
        body_lines = [
            greeting,
            "",
            f"I hope this finds you well. I'm following up again on my application for the {role} position at {company}, submitted two weeks ago.",
            "I completely understand you're managing many applications — I just wanted to reiterate my strong interest and confirm my availability for a conversation.",
            "",
            "If the position has already been filled, no worries at all — I'd still appreciate a brief note so I can plan accordingly.",
            "",
            "Thank you for your time.",
            "",
            "Best regards,",
            signature,
        ]

    else:  # rejection
        subject = f"Thank you — {role} at {company}"
        body_lines = [
            greeting,
            "",
            f"Thank you for letting me know about the {role} position at {company}.",
            "While I'm disappointed not to be moving forward this time, I genuinely appreciated the chance to learn more about your team.",
            "",
            "I'd love to stay in touch for future opportunities that might be a stronger match.",
            "In the meantime, any feedback you'd be willing to share about my application would be greatly valued.",
            "",
            "Thank you again for your time and consideration.",
            "",
            "Best regards,",
            signature,
        ]

    return f"**Subject:** {subject}\n\n---\n\n" + "\n".join(body_lines)
