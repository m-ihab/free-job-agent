"""CV Studio — ATS keyword radar against role-specific keyword packs."""
from __future__ import annotations

from typing import Any

from job_agent.config import AppConfig

_ATS_ROLE_PACKS = {
    "data_scientist": [
        "Python", "SQL", "Machine Learning", "Statistics", "Predictive Modeling",
        "Feature Engineering", "Model Evaluation", "scikit-learn", "Pandas",
        "Time Series", "NLP", "Data Visualization",
    ],
    "ml_engineer": [
        "Python", "Deep Learning", "PyTorch", "TensorFlow", "Transformers",
        "Docker", "FastAPI", "MLOps", "Model Deployment", "CI/CD",
        "Experiment Tracking", "APIs",
    ],
    "data_engineer": [
        "Python", "SQL", "ETL", "Data Pipelines", "Spark", "Airflow",
        "APIs", "Docker", "Cloud", "Data Modeling", "Automation",
    ],
    "data_analyst": [
        "SQL", "Power BI", "Tableau", "Excel", "Statistics", "Dashboards",
        "Data Cleaning", "KPI", "Reporting", "Python", "Pandas",
    ],
}


def ats_keyword_radar(config: AppConfig, text: str, role: str = "data_scientist") -> dict[str, Any]:
    """Compare the current CV draft against a role-specific ATS keyword pack."""
    pack = _ATS_ROLE_PACKS.get(role) or _ATS_ROLE_PACKS["data_scientist"]
    haystack = (text or "").casefold()
    present = [kw for kw in pack if kw.casefold() in haystack]
    missing = [kw for kw in pack if kw.casefold() not in haystack]
    coverage = round((len(present) / max(1, len(pack))) * 100)
    suggestions = [
        {
            "keyword": kw,
            "where": "skills" if kw in {"Docker", "FastAPI", "MLOps", "Power BI", "Tableau", "Spark", "Airflow"} else "projects",
            "note": "Add only if true; recruiters reward evidence more than keyword stuffing.",
        }
        for kw in missing[:8]
    ]
    return {
        "ok": True,
        "role": role,
        "coverage": coverage,
        "present": present,
        "missing": missing,
        "suggestions": suggestions,
    }
