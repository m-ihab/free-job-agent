"""Generate interview prep questions + answer frameworks for a specific job.

Grounded in the candidate's actual experience. Never invents credentials,
metrics, or technologies the candidate doesn't have.
"""
from __future__ import annotations

from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.schemas.job import JobListing


def _matching_skills(job: JobListing, profile: CandidateProfile, limit: int = 5) -> list[str]:
    candidate_lower = {s.lower() for s in profile.all_skill_names()}
    return [t for t in job.tech_stack if t.lower() in candidate_lower][:limit]


def _best_experience(master_cv: MasterCV) -> dict | None:
    if not master_cv.experience:
        return None
    exp = master_cv.experience[0]
    return exp if isinstance(exp, dict) else exp.dict() if hasattr(exp, "dict") else None


def _best_project(master_cv: MasterCV, job: JobListing) -> dict | None:
    if not master_cv.projects:
        return None
    job_techs_lower = {t.lower() for t in job.tech_stack}
    for proj in master_cv.projects:
        proj_dict = proj if isinstance(proj, dict) else proj.dict() if hasattr(proj, "dict") else {}
        techs = [t.lower() for t in proj_dict.get("technologies", [])]
        if any(t in job_techs_lower for t in techs):
            return proj_dict
    return master_cv.projects[0] if master_cv.projects else None


def generate_interview_prep(
    job: JobListing,
    master_cv: MasterCV,
    profile: CandidateProfile,
) -> str:
    """Generate interview prep sheet as Markdown.

    Covers: technical questions, behavioral (STAR), company-specific,
    and your answer talking-points grounded in your actual experience.
    """
    skills = _matching_skills(job, profile)
    exp = _best_experience(master_cv)
    proj = _best_project(master_cv, job)
    company = job.company or "this company"
    role = job.title or "this role"

    exp_company = exp.get("company", "") if exp else ""
    exp_title = exp.get("title", "") if exp else ""
    exp_bullets = exp.get("bullet_points", [])[:3] if exp else []

    proj_name = proj.get("name", "") if proj else ""
    proj_desc = proj.get("description", "") if proj else ""
    proj_techs = ", ".join(proj.get("technologies", [])[:4]) if proj else ""

    skill_str = ", ".join(skills[:3]) if skills else "data science tools"
    school = ""
    if master_cv.education:
        edu = master_cv.education[0]
        school = edu.get("institution", "") if isinstance(edu, dict) else getattr(edu, "institution", "")

    lines = [
        f"# Interview Prep — {role} at {company}",
        "",
        "---",
        "",
        "## Technical Questions",
        "",
        f"**Q1: Walk me through your experience with {skills[0] if skills else 'machine learning'}.**",
        f"Your talking point: Focus on {exp_company or 'your most recent role'} — {exp_bullets[0] if exp_bullets else 'describe a specific project or output'}.",
        "",
        f"**Q2: Describe a data pipeline or automation you built end-to-end.**",
        f"Your talking point: {exp_company} — {exp_bullets[1] if len(exp_bullets) > 1 else 'describe the input, processing steps, and output clearly'}.",
        "",
        f"**Q3: How would you explain model evaluation to a non-technical stakeholder?**",
        "Your talking point: Use an analogy (e.g., a spam filter — precision vs recall trade-off in business terms). Anchor it in a real project.",
        "",
        f"**Q4: What's your experience with {skills[1] if len(skills) > 1 else 'deep learning'}?**",
        f"Your talking point: {proj_name} — {proj_desc[:120] + '...' if proj_desc and len(proj_desc) > 120 else proj_desc}. Tech: {proj_techs}.",
        "",
        f"**Q5: How do you handle missing or noisy data?**",
        "Your talking point: Walk through imputation strategies, outlier detection, domain knowledge checks. Give a concrete example from your CV.",
        "",
        "---",
        "",
        "## Behavioral Questions (STAR Framework)",
        "",
        "**Q6: Tell me about a time you solved a complex technical problem.**",
        f"Situation: [describe context at {exp_company or 'work/school'}]",
        "Task: [what was the goal/constraint]",
        f"Action: [the specific steps you took — e.g., {exp_bullets[0] if exp_bullets else 'your approach'}]",
        "Result: [what improved — time saved, accuracy gained, stakeholder feedback]",
        "",
        "**Q7: Give an example of working in a cross-functional team.**",
        f"Situation: [relevant experience at {exp_company or school}]",
        "Task: [your role in the collaboration]",
        "Action: [how you communicated technical findings to non-technical teammates]",
        "Result: [outcome of the collaboration]",
        "",
        "**Q8: Describe a project that didn't go as planned.**",
        "Tip: Choose a REAL situation. Emphasise what you LEARNED and changed. Never blame others.",
        "",
        "---",
        "",
        "## Company-Specific Questions",
        "",
        f"**Q9: Why {company}?**",
        f"Research before interview: {company}'s recent news, tech blog, LinkedIn posts, Glassdoor reviews.",
        f"Frame as: alignment with their tech stack ({skill_str}), their domain/sector, and your career goal.",
        "",
        "**Q10: Where do you see yourself in 3 years?**",
        "Frame as: growing into a data science role in France, deepening expertise in [your strongest area], contributing to an AI-driven product team.",
        "",
        "---",
        "",
        "## Questions to Ask Them",
        "",
        "- What does a typical week look like for the data science intern?",
        "- What tools and data infrastructure does the team use?",
        "- How does the data team collaborate with product/engineering?",
        "- What would success look like at the end of the 6-month stage?",
        "- Is there potential for a permanent role or continuation?",
        "",
        "---",
        "",
        "## Red Flags to Avoid",
        "",
        "- Do NOT mention salary expectations unless asked directly",
        "- Do NOT speak negatively about previous employers",
        "- Do NOT claim skills you've only read about — be honest about depth",
        "- Do NOT give overly long answers — aim for 2 minutes per question",
        "",
    ]
    return "\n".join(lines)
