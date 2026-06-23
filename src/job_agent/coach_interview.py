"""Interview prep: likely questions + STAR scaffolds for the user's top role."""
from __future__ import annotations

from typing import Any

from job_agent.coach_catalog import _INTERVIEW_QUESTION_BANK


def _star_scaffold(experience_items: list, projects: list, query: str) -> list[dict[str, str]]:
    """Pre-fill STAR scaffolds anchored on the candidate's real artifacts."""
    scaffolds: list[dict[str, str]] = []
    for item in experience_items[:3]:
        title = getattr(item, "title", "") or ""
        company = getattr(item, "company", "") or ""
        scaffolds.append({
            "label": f"From experience: {title} at {company}",
            "situation": f"Context: my role as {title} at {company}.",
            "task": "Task: what business problem or technical goal did you own?",
            "action": "Action: which 2-3 concrete steps did you take?",
            "result": "Result: how did it land (qualitative is fine if you don't track metrics)?",
        })
    for project in projects[:2]:
        name = getattr(project, "name", "") or ""
        scaffolds.append({
            "label": f"From project: {name}",
            "situation": f"Why you started {name}: motivation + stakeholders.",
            "task": "Specific technical challenge you tackled in that project.",
            "action": "Modelling/engineering decisions you made — pros and cons of each.",
            "result": "What you learned, what you'd do differently.",
        })
    return scaffolds


def _interview_prep(profile, master_cv, gaps: list[dict]) -> dict[str, Any]:
    """Return likely interview questions + STAR scaffolds for the user.

    Heuristic role pick: choose the role family the user most often targets
    based on the candidate target_roles. Fall back to data_science.
    """
    # profile / master_cv are None on a fresh install with no profile bundle —
    # the plan is still useful (market gaps, generic questions), so degrade
    # gracefully instead of crashing.
    target_text = " ".join(
        list(getattr(profile, "target_roles", None) or []) + [getattr(profile, "summary", None) or ""]
    ).casefold()
    role = "data_science"
    if "data engineer" in target_text or "data engineering" in target_text:
        role = "data_engineering"
    elif "ml" in target_text or "machine learning" in target_text:
        role = "machine_learning"
    elif "analyst" in target_text or "analytics" in target_text:
        role = "data_analyst"
    questions = list(_INTERVIEW_QUESTION_BANK.get(role, _INTERVIEW_QUESTION_BANK["data_science"]))
    # Mix in gap-driven questions so the user practices what they're weakest on.
    for gap in gaps[:3]:
        questions.append(f"How would you ramp up on {gap['name']} in 30 days for a Paris-based team?")
    # Behavioural / fit questions French employers ask.
    questions.extend([
        "Why this team specifically — not a general 'data science' answer?",
        "Describe a time you disagreed with a manager / professor. What did you do?",
        "Decrivez vous brièvement en français.",
    ])
    scaffolds = _star_scaffold(
        getattr(master_cv, "experience", None) or [],
        getattr(master_cv, "projects", None) or [],
        target_text,
    )
    return {
        "primary_role": role,
        "questions": questions[:10],
        "star_scaffolds": scaffolds,
    }
