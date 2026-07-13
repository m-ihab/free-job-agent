"""Deterministic verdict rules for existing portfolio projects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from job_agent.evidence import EvidenceStore
from job_agent.schemas.candidate import Project

Verdict = Literal["signal", "neutral", "dilutive"]

VERDICT_RULES = (
    "Tutorial-clone names are dilutive even when they report a model metric.",
    "FJA itself and explicitly described production systems are strong signal patterns.",
    "A non-clone project with a measurable result and target-role stack overlap is signal.",
    "A project with only one of metrics or stack overlap is neutral.",
    "A project with neither metrics nor target-role stack overlap is dilutive.",
)

_TUTORIAL_NAME = re.compile(
    r"\b(tutorial|clone|todo|hello[ -]?world|titanic|iris|mnist|house[ -]?price)\b",
    re.IGNORECASE,
)
_METRIC = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|ms|s|x|rows?|users?|requests?)?\b", re.IGNORECASE)
_ROLE_STACKS = {
    "data scientist": {"python", "sql", "pandas", "numpy", "scikit learn", "sklearn", "jupyter"},
    "machine learning": {
        "python",
        "pytorch",
        "tensorflow",
        "scikit learn",
        "mlflow",
        "docker",
        "fastapi",
        "kubernetes",
    },
    "ml engineer": {
        "python",
        "pytorch",
        "tensorflow",
        "mlflow",
        "docker",
        "fastapi",
        "kubernetes",
        "aws",
        "gcp",
        "azure",
    },
    "data engineer": {"python", "sql", "spark", "airflow", "dbt", "kafka", "aws", "gcp", "azure"},
    "data analyst": {"sql", "python", "excel", "power bi", "tableau", "dbt"},
}


@dataclass(frozen=True)
class ProjectVerdict:
    name: str
    verdict: Verdict
    reasons: list[str]
    has_metrics: bool
    matched_target_stack: list[str]
    strong_pattern: str | None
    evidence_receipts: list[str]


def audit_project(
    project: Project, target_stack: set[str], evidence_store: EvidenceStore
) -> ProjectVerdict:
    text = " ".join(
        [project.name, project.description, *project.bullet_points, *project.technologies]
    )
    matched = sorted({normalise(item) for item in project.technologies} & target_stack)
    has_metrics = bool(_METRIC.search(" ".join([project.description, *project.bullet_points])))
    strong = _strong_pattern(text, project.name)
    if _TUTORIAL_NAME.search(project.name):
        verdict: Verdict = "dilutive"
        reasons = ["tutorial-clone name pattern detected"]
    elif strong:
        verdict = "signal"
        reasons = [f"recognized strong portfolio pattern: {strong}"]
    elif has_metrics and matched:
        verdict = "signal"
        reasons = ["measurable result present", "target-role stack overlap present"]
    elif has_metrics or matched:
        verdict = "neutral"
        reasons = ["only one of measurable results or target-role stack overlap is present"]
    else:
        verdict = "dilutive"
        reasons = ["no measurable result", "no target-role stack overlap"]
    if not has_metrics:
        reasons.append("no metrics found")
    receipts = [
        item.source_ref or item.source
        for item in evidence_store.all()
        if item.kind == "project" and normalise(item.label) == normalise(project.name)
    ]
    return ProjectVerdict(project.name, verdict, reasons, has_metrics, matched, strong, receipts)


def target_stack(target_roles: list[str]) -> set[str]:
    stack: set[str] = set()
    for role in target_roles:
        normalised = normalise(role)
        for role_key, skills in _ROLE_STACKS.items():
            if role_key in normalised or normalised in role_key:
                stack.update(skills)
    return stack


def normalise(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _strong_pattern(text: str, name: str) -> str | None:
    normalised_name = normalise(name)
    normalised_text = normalise(text)
    if "free job agent" in normalised_name or normalised_name == "fja":
        return "fja-itself"
    if "production system" in normalised_text or "production grade" in normalised_text:
        return "production-system"
    return None
