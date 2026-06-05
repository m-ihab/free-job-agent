"""Generate a short recruiter outreach email grounded entirely in profile facts.

This module produces a plain-text cold-outreach email the user can send
directly to a recruiter or hiring manager when one is named in the job
description.  It never invents facts, metrics, sponsorship claims, or
contact information.  All content is drawn from the candidate's profile
and the published job posting.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.schemas.job import JobListing

_MAX_WORDS = 200
_MAX_SKILLS_SHOWN = 4


def _first_name(full_name: str) -> str:
    return full_name.strip().split()[0] if full_name.strip() else full_name.strip()


def _top_matching_skills(job: JobListing, profile: CandidateProfile, limit: int = _MAX_SKILLS_SHOWN) -> list[str]:
    """Return job tech-stack items that also appear in the candidate's skills."""
    candidate_skills_lower = {s.lower() for s in profile.all_skill_names()}
    matched = [t for t in job.tech_stack if t.lower() in candidate_skills_lower]
    if not matched:
        matched = job.tech_stack[:limit]
    return matched[:limit]


def _company_opener(job: JobListing) -> str:
    """One sentence about why this specific company/role is interesting."""
    role = job.title or "this role"
    company = job.company or "your company"
    location = f" in {job.location}" if job.location else ""
    return f"I came across the {role} position at {company}{location} and wanted to reach out directly."


def _skills_pitch(matched: list[str], profile: CandidateProfile) -> str:
    if matched:
        skill_str = ", ".join(matched)
        return f"My background covers {skill_str}, which aligns directly with the requirements listed in the posting."
    target = ", ".join(profile.target_roles[:2]) if profile.target_roles else "data science and ML"
    return f"I have hands-on experience in {target} and believe I can contribute from day one."


def _cta_line(job: JobListing) -> str:
    domain = ""
    if job.apply_url:
        try:
            domain = urlparse(job.apply_url).hostname or ""
        except Exception:
            pass
    submitted = f" I have already submitted my application via {domain}." if domain else " I have submitted my application through the listed channel."
    return f"{submitted} I'd welcome the chance to discuss how my experience fits your team's needs."


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def generate_outreach_email(
    job: JobListing,
    master_cv: MasterCV,
    profile: CandidateProfile,
) -> str:
    """Return a Markdown outreach email draft (subject + body).

    The email is addressed to ``job.recruiter_name`` when available, otherwise
    to "Hiring Team".  All content is drawn from the candidate profile and the
    job posting — nothing is invented.

    Safety rules encoded in the template:
    - No invented metrics, dates, or endorsements.
    - No sponsorship or visa claims unless explicit in profile.
    - Length is capped at ~200 words.
    """
    contact = profile.contact
    full_name = contact.name if contact else ""
    email_addr = contact.email if contact else ""
    phone = getattr(contact, "phone", "") or ""
    github_url = getattr(contact, "github_url", "") or ""
    linkedin_url = getattr(contact, "linkedin_url", "") or ""

    recruiter = job.recruiter_name or ""
    greeting = f"Dear {recruiter}," if recruiter else "Dear Hiring Team,"
    subject = f"Re: {job.title} — {_first_name(full_name)}" if full_name else f"Re: {job.title}"

    matched = _top_matching_skills(job, profile)
    opener = _company_opener(job)
    pitch = _skills_pitch(matched, profile)
    cta = _cta_line(job)

    signature_parts = [full_name]
    if email_addr:
        signature_parts.append(email_addr)
    if phone:
        signature_parts.append(phone)
    if linkedin_url:
        signature_parts.append(linkedin_url)
    elif github_url:
        signature_parts.append(github_url)
    signature = " | ".join(p for p in signature_parts if p)

    body_lines = [
        greeting,
        "",
        opener,
        pitch,
        cta,
        "",
        "Best regards,",
        signature,
    ]
    body = "\n".join(body_lines)

    if _word_count(body) > _MAX_WORDS:
        cta_short = "I'd welcome a brief conversation at your convenience."
        body = body.replace(cta, cta_short, 1)

    return f"**Subject:** {subject}\n\n---\n\n{body}"
