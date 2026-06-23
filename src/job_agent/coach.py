"""Career Coach — analyzes tracked jobs vs the candidate's skills and suggests
focus areas, concrete next steps, certifications, projects, and a schedule.

Everything runs locally. When Ollama is reachable the coach asks the AI for a
qualitative reading of the candidate's gaps; otherwise it falls back to a
deterministic ranking based on the SQLite job/cache tables and the candidate
profile.

The detail lives in sibling modules so this file stays small:
  * :mod:`job_agent.coach_skills` — alias/implication maps + normalization
  * :mod:`job_agent.coach_catalog` — AI prompt + cert/project/question catalogs
  * :mod:`job_agent.coach_market` — DB-backed market + candidate-skill analysis
  * :mod:`job_agent.coach_suggestions` — deterministic certs/projects/schedule
  * :mod:`job_agent.coach_interview` — interview questions + STAR scaffolds

The AI collaborators are imported here so ``build_coach_plan`` resolves them in
this module's namespace — the seam the coach tests monkeypatch.
"""
from __future__ import annotations

from typing import Any

from job_agent.coach_catalog import _COACH_PROMPT
from job_agent.coach_interview import _interview_prep, _star_scaffold  # noqa: F401  (re-export)
from job_agent.coach_market import (  # noqa: F401  (re-export)
    _avg_fit,
    _collect_candidate_skill_evidence,
    _collect_market_skills,
    _gap_skills,
    _job_compact,
    _top_jobs_for_prompt,
    _total_tracked,
)
from job_agent.coach_skills import (  # noqa: F401  (re-export)
    SKILL_ALIASES,
    SKILL_IMPLICATIONS,
    _is_blocked_skill,
    _normalize_skill,
)
from job_agent.coach_suggestions import (  # noqa: F401  (re-export)
    _deterministic_focus,
    _deterministic_steps,
    _suggested_certs,
    _suggested_projects,
    _weekly_schedule,
)
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.validators import load_profile_bundle

try:
    from job_agent.ai_agent import (
        _candidate_summary as _ai_candidate_summary,
        _call_ollama_json as _ai_call_json,
        is_available as _ai_is_available,
    )
    from job_agent.polish import PolishOptions
except Exception:  # pragma: no cover
    _ai_candidate_summary = None  # type: ignore[assignment]
    _ai_call_json = None  # type: ignore[assignment]
    _ai_is_available = None  # type: ignore[assignment]
    PolishOptions = None  # type: ignore[assignment,misc]


def build_coach_plan(config: AppConfig) -> dict[str, Any]:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    try:
        profile, master_cv, _ = load_profile_bundle(config)
        candidate_skill_names = _collect_candidate_skill_evidence(config, master_cv)
    except Exception:
        profile = None
        master_cv = None
        candidate_skill_names = set()

    market = _collect_market_skills(db)
    gaps = _gap_skills(market, candidate_skill_names)
    total = _total_tracked(db)
    avg = _avg_fit(db)

    plan: dict[str, Any] = {
        "total_tracked": total,
        "avg_score": avg,
        "market_skills": market,
        "gap_skills": gaps,
        "top_gap": gaps[0]["name"] if gaps else None,
        "focus": _deterministic_focus(gaps),
        "steps": _deterministic_steps(gaps),
        "certifications": _suggested_certs(gaps),
        "projects": _suggested_projects(gaps),
        "headline": "",
        "source": "deterministic",
    }

    # If Ollama is reachable, ask the AI for a sharper plan.
    if _ai_is_available is not None and _ai_call_json is not None and PolishOptions is not None and profile is not None and master_cv is not None:
        try:
            options = PolishOptions.from_env()
            if _ai_is_available(options):
                prompt = (
                    _COACH_PROMPT
                    .replace("{candidate}", _ai_candidate_summary(profile, master_cv))
                    .replace("{jobs}", "\n".join(_top_jobs_for_prompt(db)) or "(no scored jobs yet)")
                )
                raw = _ai_call_json(prompt, options)
                if isinstance(raw, dict):
                    if raw.get("headline"):
                        plan["headline"] = str(raw["headline"])[:240]
                    if raw.get("top_gap"):
                        proposed_gap = _normalize_skill(str(raw["top_gap"]))
                        allowed_gaps = {_normalize_skill(g["name"]).casefold() for g in gaps}
                        if proposed_gap.casefold() in allowed_gaps:
                            plan["top_gap"] = proposed_gap[:120]
                    if isinstance(raw.get("focus"), list) and raw["focus"]:
                        plan["focus"] = [
                            {"title": str(item.get("title") or "")[:120], "why": str(item.get("why") or "")[:240]}
                            for item in raw["focus"][:6]
                            if isinstance(item, dict) and item.get("title")
                        ]
                    if isinstance(raw.get("steps"), list) and raw["steps"]:
                        plan["steps"] = [
                            {"title": str(item.get("title") or "")[:160], "deadline": str(item.get("deadline") or "")[:60]}
                            for item in raw["steps"][:8]
                            if isinstance(item, dict) and item.get("title")
                        ]
                    plan["source"] = "ai"
        except Exception:
            pass

    if not plan["headline"]:
        if gaps:
            plan["headline"] = f"Close the {gaps[0]['name']} gap and ship a public project that uses it."
        else:
            plan["headline"] = "Keep applying — the data shows you're already tracking strong matches."
    plan["schedule"] = _weekly_schedule(plan["steps"])
    plan["interview_prep"] = _interview_prep(profile, master_cv, gaps)
    return plan
