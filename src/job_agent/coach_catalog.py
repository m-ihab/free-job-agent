"""Static catalogs used by the coach: AI prompt, certifications, project
templates, and the interview question bank. Pure data — no project imports."""
from __future__ import annotations


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
