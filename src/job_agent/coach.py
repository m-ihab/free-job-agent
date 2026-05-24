"""Career Coach — analyzes tracked jobs vs the candidate's skills and suggests
focus areas, concrete next steps, and missing skills.

Everything runs locally. When Ollama is reachable the coach asks the AI for a
qualitative reading of the candidate's gaps; otherwise it falls back to a
deterministic ranking based on the SQLite job/cache tables and the candidate
profile.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

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
    _ai_candidate_summary = None
    _ai_call_json = None
    _ai_is_available = None
    PolishOptions = None


_COACH_PROMPT = """You are a career coach for a Paris-based data/AI candidate.

Given the candidate profile + a short summary of the jobs they're tracking,
write a focused, 3-piece plan in JSON only. Do not invent skills or facts that
aren't in the inputs.

{
  "headline": "one short sentence on where they should aim next",
  "top_gap": "the single most impactful skill or experience to add",
  "focus": [
    { "title": "short focus area", "why": "one sentence rationale" }, ...
  ],
  "steps": [
    { "title": "concrete action", "deadline": "this week | 2 weeks | 1 month" }, ...
  ]
}

3-5 focus areas, 4-7 steps. Steps should be specific (e.g. "Ship a small MLOps
project on GitHub using FastAPI + Docker + GitHub Actions").

CANDIDATE:
{candidate}

RECENT TRACKED JOBS (best fit first):
{jobs}

JSON:"""


def _job_compact(job_dict: dict[str, Any]) -> str:
    bits = [
        job_dict.get("title", ""),
        job_dict.get("company", ""),
        job_dict.get("ai_role_family", ""),
        job_dict.get("ai_contract", ""),
        ", ".join(job_dict.get("ai_must_haves", []) or [])[:140],
    ]
    return " | ".join(filter(None, [str(x) for x in bits]))


def _collect_market_skills(db: Database, limit: int = 12) -> list[dict[str, Any]]:
    """Aggregate the skills that recent tracked jobs ask for, using the AI
    classify cache when available and tech_stack as a fallback."""
    counter: Counter[str] = Counter()
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT id, tech_stack_json, requirements_json FROM jobs ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
        cache_rows = conn.execute(
            "SELECT job_id, payload_json FROM ai_cache WHERE kind = 'classify'"
        ).fetchall()
    cache_map: dict[str, dict] = {}
    for row in cache_rows:
        try:
            cache_map[row["job_id"]] = json.loads(row["payload_json"])
        except Exception:
            continue
    for row in rows:
        cache = cache_map.get(row["id"], {})
        must = cache.get("must_haves") or []
        for skill in must:
            if isinstance(skill, str) and skill.strip():
                counter[skill.strip()] += 3
        for skill in cache.get("nice_to_haves") or []:
            if isinstance(skill, str) and skill.strip():
                counter[skill.strip()] += 1
        try:
            stack = json.loads(row["tech_stack_json"] or "[]")
        except Exception:
            stack = []
        for skill in stack:
            if isinstance(skill, str) and skill.strip():
                counter[skill.strip()] += 1
    return [{"name": name, "count": count} for name, count in counter.most_common(limit)]


def _gap_skills(market_skills: list[dict], candidate_skills: set[str]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    have = {s.casefold() for s in candidate_skills}
    for entry in market_skills:
        name = entry["name"]
        if name.casefold() in have:
            continue
        gaps.append({"name": name, "count": entry["count"]})
        if len(gaps) >= 8:
            break
    return gaps


def _avg_fit(db: Database) -> float | None:
    with db._connect() as conn:
        row = conn.execute("SELECT AVG(fit_score) AS avg FROM jobs WHERE fit_score IS NOT NULL").fetchone()
    return round(row["avg"], 1) if row and row["avg"] is not None else None


def _total_tracked(db: Database) -> int:
    with db._connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
    return int(row["n"] if row else 0)


def _top_jobs_for_prompt(db: Database, limit: int = 8) -> list[str]:
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT title, company, fit_score, tech_stack_json FROM jobs "
            "WHERE fit_score IS NOT NULL ORDER BY fit_score DESC LIMIT ?",
            (limit,),
        ).fetchall()
    items: list[str] = []
    for row in rows:
        try:
            stack = json.loads(row["tech_stack_json"] or "[]")
        except Exception:
            stack = []
        items.append(f"- {row['title']} @ {row['company']} ({row['fit_score']}) — {', '.join(stack[:6])}")
    return items


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


def build_coach_plan(config: AppConfig) -> dict[str, Any]:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    try:
        profile, master_cv, _ = load_profile_bundle(config)
        candidate_skill_names = {s.name for s in master_cv.skills}
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
                        plan["top_gap"] = str(raw["top_gap"])[:120]
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
    return plan
