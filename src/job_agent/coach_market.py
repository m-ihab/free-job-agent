"""Market + candidate-skill analysis for the coach (reads the SQLite tables)."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from job_agent.coach_skills import (
    SKILL_ALIASES,
    SKILL_IMPLICATIONS,
    _NOISY_GAP_RE,
    _is_blocked_skill,
    _normalize_skill,
)
from job_agent.config import AppConfig
from job_agent.db.database import Database


def _job_compact(job_dict: dict[str, Any]) -> str:
    bits = [
        job_dict.get("title", ""),
        job_dict.get("company", ""),
        job_dict.get("ai_role_family", ""),
        job_dict.get("ai_contract", ""),
        ", ".join(job_dict.get("ai_must_haves", []) or [])[:140],
    ]
    return " | ".join(filter(None, [str(x) for x in bits]))


def _collect_market_skills(db: Database, limit: int = 14) -> list[dict[str, Any]]:
    """Aggregate the skills that recent tracked jobs ask for, normalized
    across French/English/aliases and stripped of buzzwords."""
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

    def _bump(skill: str, weight: int) -> None:
        if not isinstance(skill, str):
            return
        label = _normalize_skill(skill)
        if not label or len(label) < 2:
            return
        if _is_blocked_skill(label):
            return
        counter[label] += weight

    for row in rows:
        cache = cache_map.get(row["id"], {})
        for skill in cache.get("must_haves") or []:
            _bump(skill, 3)
        for skill in cache.get("nice_to_haves") or []:
            _bump(skill, 1)
        try:
            stack = json.loads(row["tech_stack_json"] or "[]")
        except Exception:
            stack = []
        for skill in stack:
            _bump(skill, 1)
    return [{"name": name, "count": count} for name, count in counter.most_common(limit)]


def _gap_skills(market_skills: list[dict], candidate_skills: set[str]) -> list[dict[str, Any]]:
    """Pick recognizable skill gaps; skip blocked / vague / phrase-style entries.

    Heuristics:
    - Drop anything in BLOCKED_GAP_TERMS.
    - Drop multi-word noun phrases that look like verb instructions
      ("analyser, structurer des données", "experimentation").
    - Drop entries longer than 28 characters — those are usually job-bullet
      fragments, not skills.
    - Require canonical-looking labels: at most 3 words, no commas.
    """
    gaps: list[dict[str, Any]] = []
    have = {_normalize_skill(s).casefold() for s in candidate_skills}
    for skill in list(candidate_skills):
        canonical = _normalize_skill(skill)
        implied_set = SKILL_IMPLICATIONS.get(canonical, set()) | SKILL_IMPLICATIONS.get(str(skill), set())
        for implied in implied_set:
            have.add(_normalize_skill(implied).casefold())
    for entry in market_skills:
        name = entry["name"]
        if name.casefold() in have:
            continue
        if _is_blocked_skill(name):
            continue
        if "," in name or len(name) > 28:
            continue
        if name.count(" ") > 2:
            continue
        if _NOISY_GAP_RE.search(name):
            continue
        gaps.append({"name": name, "count": entry["count"]})
        if len(gaps) >= 8:
            break
    return gaps


def _collect_candidate_skill_evidence(config: AppConfig, master_cv: Any | None) -> set[str]:
    """Collect skill evidence from structured profile fields and main.tex.

    This avoids false "missing" gaps when a skill is present in the curated
    LaTeX CV, in project technologies, or implied by adjacent tools.
    """
    skills: set[str] = set()
    if master_cv is not None:
        for skill in getattr(master_cv, "skills", []) or []:
            name = getattr(skill, "name", "")
            if name:
                skills.add(str(name))
        for project in getattr(master_cv, "projects", []) or []:
            for tech in getattr(project, "technologies", []) or []:
                if tech:
                    skills.add(str(tech))
            for bullet in getattr(project, "bullet_points", []) or []:
                for match in re.finditer(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9+#./ -]{1,40}", str(bullet)):
                    candidate = _normalize_skill(match.group(0))
                    if candidate != match.group(0).casefold():
                        skills.add(candidate)
        for education in getattr(master_cv, "education", []) or []:
            for item in getattr(education, "highlights", []) or []:
                for raw, canonical in SKILL_ALIASES.items():
                    if re.search(r"\b" + re.escape(raw) + r"\b", str(item), re.IGNORECASE):
                        skills.add(canonical)
    try:
        profiles_dir = config.profiles_dir
        if profiles_dir:
            main_text = (Path(profiles_dir) / "main.tex").read_text(encoding="utf-8", errors="replace")
            for raw, canonical in __import__("job_agent.coach_skills", fromlist=["SKILL_ALIASES"]).SKILL_ALIASES.items():
                if re.search(r"\b" + re.escape(raw) + r"\b", main_text, re.IGNORECASE):
                    skills.add(canonical)
            for explicit in [
                "Model Evaluation", "Feature Engineering", "Classification", "Regression",
                "Time-Series Forecasting", "MLOps", "Deep Learning", "Machine Learning",
                "TensorFlow", "PyTorch", "Power BI", "Docker", "Spark", "Hadoop",
            ]:
                if re.search(r"\b" + re.escape(explicit) + r"\b", main_text, re.IGNORECASE):
                    skills.add(explicit)
    except Exception:
        pass
    expanded = set(skills)
    for skill in skills:
        expanded.update(SKILL_IMPLICATIONS.get(_normalize_skill(skill), set()))
        expanded.update(SKILL_IMPLICATIONS.get(str(skill), set()))
    return expanded


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
