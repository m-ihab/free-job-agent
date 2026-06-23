"""Deterministic coach outputs: certifications, projects, schedule, focus, steps.

Pure functions over the gap list and the static catalogs — no DB or AI access,
so they double as the offline fallback when Ollama is unavailable.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from job_agent.coach_catalog import _CERT_SUGGESTIONS, _PROJECT_TEMPLATES


def _suggested_certs(gap_skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggested: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for gap in gap_skills[:6]:
        for cert in _CERT_SUGGESTIONS.get(gap["name"], []):
            if cert["name"] in seen_names:
                continue
            entry = dict(cert)
            entry["because"] = gap["name"]
            suggested.append(entry)
            seen_names.add(cert["name"])
            if len(suggested) >= 4:
                return suggested
    return suggested


def _suggested_projects(gap_skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    for gap in gap_skills[:6]:
        template = _PROJECT_TEMPLATES.get(gap["name"])
        if template:
            entry = dict(template)
            entry["closes_gap"] = gap["name"]
            projects.append(entry)
        if len(projects) >= 3:
            break
    return projects


def _weekly_schedule(steps: list[dict[str, Any]], today: date | None = None) -> list[dict[str, str]]:
    """Turn step deadlines into actual dated rows for the next 4 weeks."""
    today = today or date.today()
    schedule: list[dict[str, str]] = []
    week_offsets = {
        "this week": 5,
        "this-week": 5,
        "1 week": 7,
        "2 weeks": 14,
        "two weeks": 14,
        "1 month": 30,
        "one month": 30,
        "2 months": 60,
    }
    for idx, step in enumerate(steps):
        deadline_raw = (step.get("deadline") or "").strip().casefold()
        offset = week_offsets.get(deadline_raw, 7 + idx * 4)
        target = today + timedelta(days=offset)
        schedule.append({
            "week": f"Week of {target.isoformat()}",
            "title": step.get("title", ""),
            "deadline": step.get("deadline", ""),
        })
    return schedule


def _deterministic_focus(gap_skills: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Cheap fallback when AI isn't available."""
    focus = []
    for gap in gap_skills[:4]:
        focus.append({
            "title": f"Add {gap['name']}",
            "why": f"{gap['count']} recent listings asked for it.",
        })
    return focus


def _deterministic_steps(gap_skills: list[dict[str, Any]]) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    for gap in gap_skills[:3]:
        steps.append({
            "title": f"Ship a small public project using {gap['name']}",
            "deadline": "2 weeks",
        })
    steps.append({"title": "Apply to your top 3 strongest matches this week", "deadline": "this week"})
    steps.append({"title": "Refresh CV summary closing line per role", "deadline": "this week"})
    return steps
