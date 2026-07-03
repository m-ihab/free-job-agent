"""Tests for the CV Studio "key projects" picker (1-3 projects in \\projone)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from job_agent.config import AppConfig
from job_agent.cv_studio_projects import set_key_projects


def _make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    data_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir)


def _seed(config: AppConfig, projects: list[dict]) -> None:
    (Path(config.profiles_dir) / "master_cv.json").write_text(
        json.dumps({"contact": {"name": "X", "email": "x@y.z"}, "projects": projects}),
        encoding="utf-8",
    )
    (Path(config.profiles_dir) / "main.tex").write_text(
        "\\newcommand{\\projone}{\\cvitem{\\textbf{Old}}{Old body.}}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )


_PROJECTS = [
    {"name": "Fraud Detector", "description": "Real-time fraud detection", "technologies": ["python", "xgboost"]},
    {"name": "Churn Model", "description": "Churn prediction pipeline", "technologies": ["python", "airflow"]},
    {"name": "Doc Search", "description": "Semantic document search", "technologies": ["python", "faiss"]},
]


def test_set_key_projects_packs_two_projects_into_projone(tmp_path):
    config = _make_config(tmp_path)
    _seed(config, _PROJECTS)
    result = set_key_projects(config, 2)
    assert result["ok"] is True
    assert result["count"] == 2
    text = result["text"]
    assert "Fraud Detector" in text
    assert "Churn Model" in text
    assert "Doc Search" not in text
    # Still exactly one \projone definition.
    assert len(re.findall(r"\\newcommand\{\\projone\}", text)) == 1


def test_set_key_projects_count_clamped_to_available(tmp_path):
    config = _make_config(tmp_path)
    _seed(config, _PROJECTS[:1])
    result = set_key_projects(config, 3)
    assert result["ok"] is True
    assert result["count"] == 1


def test_set_key_projects_single_keeps_shape(tmp_path):
    config = _make_config(tmp_path)
    _seed(config, _PROJECTS)
    result = set_key_projects(config, 1)
    assert result["ok"] is True
    assert "Fraud Detector" in result["text"]
    assert "Churn Model" not in result["text"]


def test_set_key_projects_without_projects_fails(tmp_path):
    config = _make_config(tmp_path)
    _seed(config, [])
    result = set_key_projects(config, 2)
    assert result["ok"] is False
    assert result["reason"] == "no_projects"


def test_set_key_projects_without_cv_source_fails(tmp_path):
    config = _make_config(tmp_path)
    (Path(config.profiles_dir) / "master_cv.json").write_text(
        json.dumps({"contact": {"name": "X", "email": "x@y.z"}, "projects": _PROJECTS}),
        encoding="utf-8",
    )
    result = set_key_projects(config, 2)
    assert result["ok"] is False
    assert result["reason"] == "no_cv_source"
