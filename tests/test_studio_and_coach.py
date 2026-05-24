from __future__ import annotations

import json

from job_agent.coach import _gap_skills
from job_agent.config import AppConfig
from job_agent.cv_studio import compile_preview, save_project
from job_agent.generator.company_extract import extract_real_company, looks_unusable_company
from job_agent.schemas.job import JobListing


def test_studio_rejects_json_as_compile_input(tmp_path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "main.tex").write_text("\\begin{document}ok\\end{document}", encoding="utf-8")
    cfg = AppConfig(data_dir=tmp_path / "data", profiles_dir=profiles)

    result = compile_preview(cfg, '{"contact": {}}')

    assert result["ok"] is False
    assert result["reason"] == "not_latex_document"
    assert "asset editor" in result["log"]


def test_studio_saves_and_promotes_team_project(tmp_path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "master_cv.json").write_text(json.dumps({"projects": []}), encoding="utf-8")
    cfg = AppConfig(data_dir=tmp_path / "data", profiles_dir=profiles)

    result = save_project(
        cfg,
        {
            "name": "DSTI Deep Learning AG News Classifier",
            "description": "Transformer NLP classifier",
            "url": "https://github.com/fractalical/dsti-deep-learning",
            "technologies": ["Python", "DistilBERT", "RoBERTa"],
            "bullet_points": ["Owned model-development and training workflow."],
        },
    )

    assert result["ok"] is True
    data = json.loads((profiles / "master_cv.json").read_text(encoding="utf-8"))
    assert data["projects"][0]["name"] == "DSTI Deep Learning AG News Classifier"


def test_company_extraction_rejects_sentence_fragments():
    assert looks_unusable_company("Vous êtes à la") is True
    job = JobListing(
        title="Analyste de données H/F en apprentissage",
        company="France Travail",
        description="Vous êtes à la recherche d'une opportunité ? L'Agence Nationale de la Recherche (ANR) vous offre la possibilité de rejoindre son équipe.",
    )

    assert extract_real_company(job) == "Agence Nationale de la Recherche"


def test_company_extraction_prefers_earliest_real_company_over_tool_mentions():
    job = JobListing(
        title="Data Engineering MANAGER (H/F) CDI",
        company="France Travail",
        description="Histoire d'Or est le leader du marché. Stack: Snowflake, SAP, Power BI.",
    )

    assert extract_real_company(job) == "Histoire d'Or"


def test_coach_gap_skips_skills_implied_by_profile():
    market = [
        {"name": "Machine Learning", "count": 20},
        {"name": "Statistics", "count": 13},
        {"name": "MLOps", "count": 10},
        {"name": "Tableau", "count": 8},
    ]
    have = {"Deep Learning", "Model Evaluation", "Docker", "FastAPI", "Power BI"}

    assert _gap_skills(market, have) == []
