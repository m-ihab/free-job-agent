"""Skill normalization, alias/implication maps, and gap-term blocklist.

Pure data + helpers shared across the coach modules. Imports nothing from the
project, so it is safe to import anywhere without risking an import cycle.
"""
from __future__ import annotations

import re

# Normalized labels for skills that appear under multiple names (French /
# English / acronyms). Used to merge counters so "modélisation", "modeling",
# and "ML" don't all surface as separate gaps when they're the same competence.
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
}


_NOISY_GAP_RE = re.compile(
    r"\b(analyser|exploiter|structurer|exp[ée]rimenter|d[ée]velopper|appliquer|mettre|"
    r"experimentation|analytics|analyse|analysis|data analytics|reporting|visualisation|"
    r"visualization|recherche)\b",
    re.IGNORECASE,
)


def _normalize_skill(raw: str) -> str:
    cleaned = (raw or "").strip().casefold()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .,;:()/'\"")
    return SKILL_ALIASES.get(cleaned, cleaned)


def _is_blocked_skill(label: str) -> bool:
    return label.casefold() in _BLOCKED_GAP_TERMS
