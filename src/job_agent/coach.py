"""Career Coach — analyzes tracked jobs vs the candidate's skills and suggests
focus areas, concrete next steps, certifications, projects, and a schedule.

Everything runs locally. When Ollama is reachable the coach asks the AI for a
qualitative reading of the candidate's gaps; otherwise it falls back to a
deterministic ranking based on the SQLite job/cache tables and the candidate
profile.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any


# Normalized labels for skills that appear under multiple names (French /
# English / acronyms). Used to merge counters so "modélisation",
# "modeling", and "ML" don't all surface as separate gaps when they're
# basically the same competence.
SKILL_ALIASES: dict[str, str] = {
    "modélisation": "Machine Learning",
    "modelisation": "Machine Learning",
    "modeling": "Machine Learning",
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "apprentissage automatique": "Machine Learning",
    "statistiques": "Statistics",
    "statistics": "Statistics",
    "stats": "Statistics",
    "intelligence artificielle": "Artificial Intelligence",
    "ia": "Artificial Intelligence",
    "ai": "Artificial Intelligence",
    "deep learning": "Deep Learning",
    "apprentissage profond": "Deep Learning",
    "données": "Data",
    "donnees": "Data",
    "data": "Data",
    "mlops": "MLOps",
    "tableau": "Tableau",
    "power bi": "Power BI",
    "powerbi": "Power BI",
    "python": "Python",
    "sql": "SQL",
    "r": "R",
    "scala": "Scala",
    "spark": "Spark",
    "hadoop": "Hadoop",
    "airflow": "Airflow",
    "kafka": "Kafka",
    "dbt": "dbt",
    "snowflake": "Snowflake",
    "bigquery": "BigQuery",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "git": "Git",
    "github actions": "GitHub Actions",
    "ci/cd": "CI/CD",
    "ci cd": "CI/CD",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "scikit-learn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "nlp": "NLP",
    "natural language processing": "NLP",
    "computer vision": "Computer Vision",
    "rag": "RAG",
    "llm": "LLM",
    "llms": "LLM",
    "transformer": "Transformers",
    "transformers": "Transformers",
    "azure": "Azure",
    "aws": "AWS",
    "gcp": "GCP",
    "google cloud": "GCP",
    "sap btp": "SAP BTP",
    "excel": "Excel",
    "vba": "VBA",
    "etl": "ETL",
    "elt": "ELT",
    "data engineering": "Data Engineering",
    "data science": "Data Science",
}

SKILL_IMPLICATIONS: dict[str, set[str]] = {
    "Machine Learning": {"Artificial Intelligence", "Statistics", "modélisation", "modeling", "ML"},
    "Deep Learning": {"Artificial Intelligence", "Machine Learning", "ML", "AI"},
    "Model Evaluation": {"Statistics", "Machine Learning"},
    "Survival Analysis": {"Statistics", "Machine Learning"},
    "Power BI": {"Business Intelligence", "Tableau", "Data Visualization"},
    "Matplotlib": {"Data Visualization", "Tableau"},
    "Seaborn": {"Data Visualization", "Tableau"},
    "Docker": {"MLOps"},
    "FastAPI": {"MLOps"},
    "CI/CD": {"MLOps"},
    "GitHub Actions": {"MLOps"},
    "TensorFlow": {"Deep Learning", "Machine Learning", "Artificial Intelligence"},
    "PyTorch": {"Deep Learning", "Machine Learning", "Artificial Intelligence"},
    "Transformers": {"Deep Learning", "NLP", "LLM", "Artificial Intelligence"},
    "NLP": {"LLM", "Artificial Intelligence"},
}


# Words that are too vague to recommend as a "skill gap" — they're either
# generic concepts every job mentions, or they're business buzzwords.
_BLOCKED_GAP_TERMS = {
    "data", "team", "english", "français", "francais", "communication", "agile",
    "analyse", "analysis", "rigueur", "autonomie", "leadership", "esprit",
    "esprit d'équipe", "esprit dequipe", "qualité", "qualite", "production",
    "industriel", "industrielle", "performance", "innovation", "stratégie",
    "strategie", "strategy", "management", "junior", "senior", "stage",
    "alternance", "internship", "anglais", "client", "clients",
    "communication",  # repeat dedup
}


def _normalize_skill(raw: str) -> str:
    cleaned = (raw or "").strip().casefold()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .,;:()/'\"")
    return SKILL_ALIASES.get(cleaned, cleaned)


def _is_blocked_skill(label: str) -> bool:
    return label.casefold() in _BLOCKED_GAP_TERMS

from job_agent.config import AppConfig  # noqa: E402  (intentional: after module helpers to avoid an import cycle)
from job_agent.db.database import Database  # noqa: E402
from job_agent.validators import load_profile_bundle  # noqa: E402


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


_NOISY_GAP_RE = re.compile(
    r"\b(analyser|exploiter|structurer|exp[ée]rimenter|d[ée]velopper|appliquer|mettre|"
    r"experimentation|analytics|analyse|analysis|data analytics|reporting|visualisation|"
    r"visualization|recherche)\b",
    re.IGNORECASE,
)


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
            for raw, canonical in SKILL_ALIASES.items():
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


# Curated, label-keyed certification suggestions. We pick certs that are
# valuable for Paris data/AI roles and add the matching gap as the reason
# we're suggesting it. Empty list when the candidate has the skill already.
_CERT_SUGGESTIONS = {
    "MLOps": [
        {"name": "AWS Certified Machine Learning – Specialty", "url": "https://aws.amazon.com/certification/certified-machine-learning-specialty/", "duration": "6-10 weeks", "free_path": "AWS Skill Builder + practice exam from ExamPro YouTube"},
        {"name": "Google Cloud Professional Machine Learning Engineer", "url": "https://cloud.google.com/certification/machine-learning-engineer", "duration": "8-12 weeks", "free_path": "Google Cloud Skills Boost free credits"},
        {"name": "MLOps Specialization (Coursera, audit free)", "url": "https://www.coursera.org/specializations/machine-learning-engineering-for-production-mlops", "duration": "8 weeks", "free_path": "Coursera audit + DeepLearning.AI labs"},
    ],
    "Deep Learning": [
        {"name": "DeepLearning.AI Specialization", "url": "https://www.coursera.org/specializations/deep-learning", "duration": "10 weeks", "free_path": "Coursera audit"},
        {"name": "fast.ai Practical Deep Learning", "url": "https://course.fast.ai/", "duration": "7 weeks", "free_path": "Free, official"},
    ],
    "NLP": [
        {"name": "Hugging Face NLP Course", "url": "https://huggingface.co/learn/nlp-course", "duration": "5 weeks", "free_path": "Free, official"},
        {"name": "DeepLearning.AI NLP Specialization", "url": "https://www.coursera.org/specializations/natural-language-processing", "duration": "8 weeks", "free_path": "Coursera audit"},
    ],
    "LLM": [
        {"name": "LangChain Academy", "url": "https://academy.langchain.com/", "duration": "2 weeks", "free_path": "Free intro courses"},
        {"name": "DeepLearning.AI Short Courses on LLM/RAG", "url": "https://learn.deeplearning.ai/", "duration": "1 week each", "free_path": "Free"},
    ],
    "Data Engineering": [
        {"name": "DataTalksClub Data Engineering Zoomcamp", "url": "https://github.com/DataTalksClub/data-engineering-zoomcamp", "duration": "9 weeks", "free_path": "Free, community-led"},
        {"name": "Google Cloud Professional Data Engineer", "url": "https://cloud.google.com/certification/data-engineer", "duration": "8-12 weeks", "free_path": "Coursera audit + Skills Boost"},
    ],
    "AWS": [
        {"name": "AWS Certified Cloud Practitioner", "url": "https://aws.amazon.com/certification/certified-cloud-practitioner/", "duration": "4 weeks", "free_path": "AWS Skill Builder free path"},
    ],
    "GCP": [
        {"name": "Google Cloud Digital Leader", "url": "https://cloud.google.com/certification/cloud-digital-leader", "duration": "3 weeks", "free_path": "Skills Boost"},
    ],
    "Azure": [
        {"name": "Microsoft Azure AI Fundamentals (AI-900)", "url": "https://learn.microsoft.com/credentials/certifications/azure-ai-fundamentals/", "duration": "3 weeks", "free_path": "Microsoft Learn (free)"},
    ],
    "Power BI": [
        {"name": "Microsoft PL-300 Power BI Data Analyst", "url": "https://learn.microsoft.com/credentials/certifications/data-analyst-associate/", "duration": "5 weeks", "free_path": "Microsoft Learn (free)"},
    ],
    "Tableau": [
        {"name": "Tableau Desktop Specialist", "url": "https://www.tableau.com/learn/certification/desktop-specialist", "duration": "3 weeks", "free_path": "Free training videos"},
    ],
    "Spark": [
        {"name": "Databricks Lakehouse Fundamentals (free)", "url": "https://www.databricks.com/learn/certification/lakehouse-fundamentals", "duration": "1 week", "free_path": "Free"},
    ],
    "Statistics": [
        {"name": "Stanford 'Statistical Learning' (edX, audit free)", "url": "https://www.edx.org/learn/statistical-analysis", "duration": "6 weeks", "free_path": "edX audit"},
    ],
}


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


# Compact project templates keyed by gap skill — every project ties to a real,
# free toolchain and produces a portfolio-ready output.
_PROJECT_TEMPLATES = {
    "MLOps": {
        "title": "Production-ready model service",
        "summary": "Wrap an existing model (your forecasting/cyber project) into a FastAPI service inside Docker, push to GitHub with CI, deploy a free demo on Hugging Face Spaces.",
        "deliverable": "Public repo + live demo + README that documents the deploy workflow.",
        "duration": "1-2 weekends",
    },
    "LLM": {
        "title": "RAG demo over your own CV + job postings",
        "summary": "Build a small RAG app with LangChain or LlamaIndex that lets you ask questions about your CV and job descriptions.",
        "deliverable": "Streamlit demo + repo with prompt + retrieval code.",
        "duration": "1 weekend",
    },
    "Deep Learning": {
        "title": "End-to-end image or text classifier",
        "summary": "Pick a clean dataset (Kaggle / Hugging Face) and ship a notebook + script + small Streamlit demo using PyTorch/TF.",
        "deliverable": "Notebook, model card, Streamlit demo on HF Spaces.",
        "duration": "1-2 weekends",
    },
    "Data Engineering": {
        "title": "Dockerized data pipeline with Airflow or dbt",
        "summary": "Ingest a public API daily, model it with dbt or Airflow, store in DuckDB or BigQuery free tier, surface as a small dashboard.",
        "deliverable": "Repo + pipeline diagram + sample Looker Studio dashboard.",
        "duration": "2 weekends",
    },
    "NLP": {
        "title": "French/English NLP demo",
        "summary": "Build a bilingual classifier (sentiment, topic) using Hugging Face transformers + tokenizers; demo on Spaces.",
        "deliverable": "Repo + demo + comparison notebook between two models.",
        "duration": "1-2 weekends",
    },
    "Power BI": {
        "title": "Public Power BI report",
        "summary": "Take a public French dataset (data.gouv.fr) and build an analytical report with DAX measures.",
        "deliverable": "Published Power BI report + repo with PBIX and screenshots.",
        "duration": "1 weekend",
    },
    "Spark": {
        "title": "Spark notebook on Databricks Community",
        "summary": "Use the free Databricks Community Edition to process a Kaggle dataset with PySpark.",
        "deliverable": "Notebook + write-up explaining when Spark beats Pandas.",
        "duration": "1 weekend",
    },
}


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


# ---------------------------------------------------------------------------
# Interview prep — likely questions + STAR scaffolds for the user's top role.
# ---------------------------------------------------------------------------


_INTERVIEW_QUESTION_BANK = {
    "data_science": [
        "Walk me through a project where you applied a statistical or ML model end-to-end.",
        "How would you detect concept drift in production?",
        "Pick a deep-learning project of yours: what was the validation strategy and what went wrong first?",
        "Explain bias-variance trade-off using one of your past models.",
        "How do you handle class imbalance? What did you actually try last time?",
        "Explain a time you had to compromise model accuracy for latency or interpretability.",
    ],
    "machine_learning": [
        "Describe an MLOps pipeline you would build for one of your projects.",
        "How do you decide between a baseline model, a tree ensemble, and deep learning?",
        "Walk me through hyper-parameter tuning on your most demanding project.",
        "How do you monitor a deployed model? What metrics matter and why?",
        "Describe an end-to-end retraining cadence for a time-series forecaster.",
    ],
    "data_engineering": [
        "Sketch a daily pipeline from a public API to an analytical dashboard.",
        "Where would you draw the line between Pandas and Spark on a 50 GB dataset?",
        "Describe ETL versus ELT — which fits your last project and why?",
        "What's your data-quality strategy for upstream data you don't own?",
        "Walk me through an incident in a pipeline you owned: detection, mitigation, fix.",
    ],
    "data_analyst": [
        "Take a metric you reported and explain why a stakeholder should trust it.",
        "Walk me through an A/B test you ran: hypothesis, design, post-analysis.",
        "Show me a dashboard you'd build for a finance team and the questions it answers.",
        "How do you handle conflicting numbers from two business owners?",
    ],
}


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
