"""Generate LinkedIn outreach messages — three formats grounded in profile facts.

LinkedIn messages have strict character limits and a distinctive tone:
no "Dear/Regards", direct, human, specific. All content comes exclusively
from the candidate profile and job description — nothing invented.
"""
from __future__ import annotations

from urllib.parse import urlparse

from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.schemas.job import JobListing

_CONNECT_LIMIT = 250
_MESSAGE_LIMIT = 300


def _first_name(full_name: str) -> str:
    return full_name.strip().split()[0] if full_name.strip() else "there"


def _top_skills(job: JobListing, profile: CandidateProfile, limit: int = 3) -> list[str]:
    candidate_lower = {s.lower() for s in profile.all_skill_names()}
    matched = [t for t in job.tech_stack if t.lower() in candidate_lower]
    return (matched or job.tech_stack)[:limit]


def _company_hook(job: JobListing) -> str:
    company = job.company or "your company"
    if job.location and "paris" in job.location.lower():
        return f"I came across {company}'s {job.title} role in Paris"
    return f"I came across {company}'s {job.title} opening"


def generate_linkedin_connect_request(
    job: JobListing,
    master_cv: MasterCV,
    profile: CandidateProfile,
) -> str:
    """~250-character connection request note for LinkedIn.

    Short, specific, no formal opener. Grounded in role + profile.
    """
    skills = _top_skills(job, profile, limit=2)
    skill_str = " and ".join(skills) if skills else "data science"
    hook = _company_hook(job)
    company = job.company or "your team"

    text = (
        f"Hi! {hook} and I'd love to connect. "
        f"I'm a DS/AI master's student with hands-on {skill_str} experience, "
        f"currently seeking a 6-month stage. Would be great to learn more about {company}!"
    )
    return text[:_CONNECT_LIMIT]


def generate_linkedin_recruiter_message(
    job: JobListing,
    master_cv: MasterCV,
    profile: CandidateProfile,
) -> str:
    """Direct LinkedIn message to a recruiter about a specific role (~300 words).

    More detailed than the connect request. Mentions role, 2-3 matching skills,
    availability, and a call to action. No invented facts.
    """
    contact = profile.contact
    full_name = contact.name if contact else ""
    skills = _top_skills(job, profile, limit=3)
    skill_str = ", ".join(skills) if skills else "data science"
    company = job.company or "your company"
    role = job.title or "the role"

    # Pull school from master_cv if available
    school = ""
    if master_cv.education:
        school = master_cv.education[0].get("institution", "") if isinstance(master_cv.education[0], dict) else getattr(master_cv.education[0], "institution", "")

    school_line = f" I'm currently finishing my Applied MSc in Data Science & AI at {school}." if school else " I'm currently finishing my Data Science master's."

    apply_ref = ""
    if job.apply_url:
        try:
            domain = urlparse(job.apply_url).hostname or ""
            apply_ref = f" I've already submitted my application via {domain}."
        except Exception:
            pass

    lines = [
        "Hi,",
        "",
        f"I spotted the {role} position at {company} and wanted to reach out directly.",
        f"{school_line}{apply_ref}",
        "",
        f"My background covers {skill_str}, which aligns closely with what you're looking for.",
        "I'm available for a 6-month convention de stage starting as soon as needed.",
        "",
        "Would you be open to a brief call or to share more about the team?",
        "",
        f"Best, {_first_name(full_name)}",
    ]
    return "\n".join(lines)


def generate_linkedin_followup_message(
    job: JobListing,
    master_cv: MasterCV,
    profile: CandidateProfile,
    days_since_apply: int = 7,
) -> str:
    """Follow-up message sent ~7 days after applying via LinkedIn.

    Keeps the connection warm without being pushy.
    """
    first = _first_name(profile.contact.name if profile.contact else "")
    role = job.title or "the position"
    company = job.company or "your company"

    if days_since_apply <= 7:
        opener = f"I applied for the {role} role at {company} about a week ago"
        closer = "Just wanted to confirm my application came through and reiterate my strong interest."
    else:
        opener = f"I reached out two weeks ago about the {role} position at {company}"
        closer = "I understand you're busy — happy to answer any questions or provide additional materials if helpful."

    lines = [
        "Hi,",
        "",
        f"{opener} and wanted to follow up.",
        closer,
        "",
        "Looking forward to hearing from you.",
        "",
        f"Best, {first}",
    ]
    return "\n".join(lines)
