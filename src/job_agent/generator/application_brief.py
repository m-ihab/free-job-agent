"""Per-application brief: a headline, a short summary, and role keywords.

All three are built deterministically from real profile + job fields (never
invented), so they are safe by construction. The dashboard can optionally route
the headline/summary through the Smart engine for warmer wording, but the
deterministic output here is always the grounded baseline and fallback.
"""
from __future__ import annotations

from typing import Any

_MAX_KEYWORDS = 12
_MAX_HEADLINE_SKILLS = 3


def _matched_skills(job: Any, profile: Any) -> list[str]:
    """Job tech-stack items the candidate actually has, in posting order."""
    try:
        candidate = {s.lower() for s in profile.all_skill_names()}
    except Exception:
        candidate = set()
    seen: set[str] = set()
    matched: list[str] = []
    for tech in getattr(job, "tech_stack", []) or []:
        key = tech.lower()
        if key in candidate and key not in seen:
            seen.add(key)
            matched.append(tech)
    return matched


def extract_role_keywords(job: Any, profile: Any, limit: int = _MAX_KEYWORDS) -> list[str]:
    """Most relevant keywords for the role.

    Ranks the job's tech stack with the candidate's *proven* skills first (worth
    featuring) followed by the remaining role-required skills. De-duplicated
    case-insensitively and capped at ``limit``.
    """
    try:
        candidate = {s.lower() for s in profile.all_skill_names()}
    except Exception:
        candidate = set()
    matched: list[str] = []
    required: list[str] = []
    seen: set[str] = set()
    for tech in getattr(job, "tech_stack", []) or []:
        key = (tech or "").lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        (matched if key in candidate else required).append(tech)
    return (matched + required)[:limit]


def generate_headline(job: Any, master_cv: Any, profile: Any) -> str:
    """A single-line positioning headline for this application."""
    role = getattr(job, "title", "") or "Data role"
    company = getattr(job, "company", "") or "your team"
    skills = _matched_skills(job, profile)[:_MAX_HEADLINE_SKILLS]
    if not skills:
        skills = (getattr(job, "tech_stack", []) or [])[:_MAX_HEADLINE_SKILLS]
    if skills:
        skill_str = ", ".join(skills[:-1]) + (f" & {skills[-1]}" if len(skills) > 1 else skills[0])
        if len(skills) == 1:
            skill_str = skills[0]
        return f"{role} application — {skill_str} for {company}"
    return f"{role} application — {company}"


def generate_summary(job: Any, master_cv: Any, profile: Any) -> str:
    """A 2–3 sentence, fully grounded application summary."""
    role = getattr(job, "title", "") or "the role"
    company = getattr(job, "company", "") or "your team"
    location = getattr(job, "location", "") or ""
    where = f" in {location}" if location else ""
    matched = _matched_skills(job, profile)
    roles = getattr(profile, "target_roles", []) or []

    if matched:
        skill_str = ", ".join(matched[:4])
        fit = (f"My background in {skill_str} maps directly to what the {role} "
               f"posting asks for.")
    elif roles:
        fit = (f"I'm targeting {', '.join(roles[:2])} roles and believe I can "
               f"contribute from day one.")
    else:
        fit = "I believe my background aligns closely with the posting."

    return (f"Application for the {role} role at {company}{where}. {fit} "
            f"I'd welcome the chance to discuss how I can add value to the team.")


def build_application_brief(job: Any, master_cv: Any, profile: Any) -> dict[str, Any]:
    """Bundle the headline, summary, and role keywords for one application."""
    return {
        "headline": generate_headline(job, master_cv, profile),
        "summary": generate_summary(job, master_cv, profile),
        "keywords": extract_role_keywords(job, profile),
    }
