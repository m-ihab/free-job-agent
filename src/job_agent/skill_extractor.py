"""Implicit skill extractor + job keyword gap miner.

Two sources of missing skills:
1. Tech-stack inference: skills that are logically implied by what you list
   (Flask → REST API; Transformers → Hugging Face; Docker → containerisation)
2. Job keyword mining: high-frequency terms across all tracked jobs that are
   absent from your skill list — the ATS gap you can close cheaply.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.schemas.job import JobListing


# Maps an existing skill (lowercase) → implied skills that should also be listed
_IMPLICATION_MAP: dict[str, list[str]] = {
    "flask":        ["REST API", "Jinja2", "WSGI", "HTTP"],
    "django":       ["REST API", "ORM", "MVC", "Django REST Framework"],
    "react":        ["JavaScript", "JSX", "Frontend Development", "Node.js"],
    "node.js":      ["JavaScript", "REST API", "NPM"],
    "docker":       ["Containerisation", "Docker Compose", "DevOps"],
    "kubernetes":   ["Containerisation", "Orchestration", "DevOps"],
    "transformers": ["Hugging Face", "Fine-tuning", "NLP", "BERT"],
    "distilbert":   ["Hugging Face", "Transformers", "Transfer Learning"],
    "roberta":      ["Hugging Face", "Transformers", "Transfer Learning"],
    "bert":         ["Hugging Face", "Transformers", "NLP"],
    "scikit-learn": ["Feature Engineering", "Model Evaluation", "Cross-Validation", "Pipeline"],
    "pytorch":      ["Deep Learning", "Neural Networks", "Backpropagation", "CUDA"],
    "tensorflow":   ["Deep Learning", "Neural Networks", "Keras"],
    "xgboost":      ["Gradient Boosting", "Ensemble Methods", "Feature Importance"],
    "spark":        ["Distributed Computing", "Big Data", "PySpark", "Hadoop"],
    "apache spark": ["Distributed Computing", "Big Data", "PySpark"],
    "pyspark":      ["Apache Spark", "Distributed Computing", "Big Data"],
    "ci/cd":        ["GitHub Actions", "DevOps", "Automation", "Jenkins"],
    "github actions": ["CI/CD", "DevOps", "Automation"],
    "airflow":      ["DAG", "Workflow Orchestration", "ETL", "Scheduling"],
    "dbt":          ["SQL", "Data Transformation", "ELT", "Analytics Engineering"],
    "neo4j":        ["Graph Database", "Cypher", "NoSQL"],
    "mlflow":       ["MLOps", "Experiment Tracking", "Model Registry"],
    "mlops":        ["MLflow", "Model Deployment", "Experiment Tracking"],
    "survival analysis": ["Kaplan-Meier", "Cox Model", "Lifelines"],
    "time-series forecasting": ["ARIMA", "Prophet", "Statsmodels", "Seasonality"],
    "power bi":     ["DAX", "Data Visualisation", "Business Intelligence"],
    "pandas":       ["Data Wrangling", "Data Cleaning", "ETL"],
    "numpy":        ["Linear Algebra", "Numerical Computing"],
    "excel":        ["Pivot Tables", "Data Analysis", "VBA"],
    "vba":          ["Macro Automation", "Excel", "Office Automation"],
    "sap btp":      ["Cloud Architecture", "Data Governance", "ERP"],
    "r":            ["Statistical Analysis", "ggplot2", "Statistical Modeling"],
    "pca":          ["Dimensionality Reduction", "Feature Reduction", "Unsupervised Learning"],
    "random forest": ["Ensemble Methods", "Decision Trees", "Feature Importance"],
    "aws":          ["Cloud Computing", "S3", "EC2", "Lambda"],
    "gcp":          ["Cloud Computing", "BigQuery", "Google Cloud"],
    "jupyter notebook": ["Data Analysis", "Exploratory Data Analysis"],
    "git":          ["Version Control", "GitHub", "Branching"],
    "deep learning": ["Neural Networks", "Backpropagation", "PyTorch", "TensorFlow"],
    "nlp":          ["Text Processing", "Tokenisation", "Sentiment Analysis"],
    "agile":        ["Scrum", "Sprint Planning", "Jira"],
}

_TREND_SKILLS_2025 = [
    "LLM", "RAG", "LangChain", "Hugging Face", "Fine-tuning", "Prompt Engineering",
    "MLOps", "MLflow", "dbt", "Apache Spark", "Airflow", "Feature Engineering",
    "Graph Neural Networks", "Transformers", "NLP", "Vector Database",
    "FastAPI", "CI/CD", "GitHub Actions", "Docker", "Kubernetes",
]


@dataclass
class ImpliedSkill:
    name: str
    implied_by: str
    category: str = "general"


@dataclass
class KeywordGap:
    skill: str
    frequency: int
    jobs_count: int
    example_titles: list[str]


def extract_implied_skills(
    profile: CandidateProfile,
    master_cv: MasterCV,
) -> list[ImpliedSkill]:
    """Return skills logically implied by the profile but not explicitly listed."""
    existing = {s.lower() for s in profile.all_skill_names()}
    implied: list[ImpliedSkill] = []
    seen: set[str] = set()

    for skill in profile.all_skill_names():
        key = skill.lower()
        for implied_skills in _IMPLICATION_MAP.get(key, []):
            if implied_skills.lower() not in existing and implied_skills.lower() not in seen:
                seen.add(implied_skills.lower())
                implied.append(ImpliedSkill(name=implied_skills, implied_by=skill))

    # Also check project technologies in master_cv
    for proj in (master_cv.projects or []):
        techs = proj.get("technologies", []) if isinstance(proj, dict) else getattr(proj, "technologies", [])
        for tech in techs:
            key = tech.lower()
            for implied_name in _IMPLICATION_MAP.get(key, []):
                if implied_name.lower() not in existing and implied_name.lower() not in seen:
                    seen.add(implied_name.lower())
                    implied.append(ImpliedSkill(name=implied_name, implied_by=tech))

    return implied


def mine_job_keywords(
    tracked_jobs: list[JobListing],
    profile: CandidateProfile,
    top_n: int = 20,
    min_frequency: int = 2,
) -> list[KeywordGap]:
    """Find high-frequency ATS keywords in tracked jobs that are absent from profile."""
    if not tracked_jobs:
        return []

    existing = {s.lower() for s in profile.all_skill_names()}
    tech_counter: Counter[str] = Counter()
    tech_jobs: dict[str, list[str]] = {}

    for job in tracked_jobs:
        seen_in_job: set[str] = set()
        for tech in job.tech_stack:
            norm = tech.strip()
            key = norm.lower()
            if key not in existing and key not in seen_in_job:
                tech_counter[norm] += 1
                if norm not in tech_jobs:
                    tech_jobs[norm] = []
                tech_jobs[norm].append(job.title)
                seen_in_job.add(key)

    gaps = [
        KeywordGap(
            skill=tech,
            frequency=count,
            jobs_count=count,
            example_titles=tech_jobs.get(tech, [])[:3],
        )
        for tech, count in tech_counter.most_common(top_n)
        if count >= min_frequency
    ]
    return gaps


def suggest_trend_gaps(profile: CandidateProfile) -> list[str]:
    """Return 2025 trending skills not in the profile."""
    existing = {s.lower() for s in profile.all_skill_names()}
    return [s for s in _TREND_SKILLS_2025 if s.lower() not in existing]
