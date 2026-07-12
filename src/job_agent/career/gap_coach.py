"""Deterministic market-gap analysis over scored jobs in the local database."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

from job_agent.career.gap_simulation import SimulatedScoreLift, simulate_score_lift
from job_agent.db.database import Database
from job_agent.evidence import EvidenceStore
from job_agent.generator.ats_gap import compute_ats_gap
from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing
from job_agent.scorer import explain_score, score_job

_SKILL_FAMILIES = (
    ("MLOps / deployment", ("docker", "kubernetes", "k8s", "mlflow", "mlops", "deployment", "model registry")),
    ("Data engineering", ("spark", "pyspark", "airflow", "dbt", "etl", "data engineering")),
    ("Cloud platforms", ("aws", "azure", "gcp", "google cloud", "bigquery")),
    ("Machine learning", ("scikit", "sklearn", "tensorflow", "pytorch", "deep learning", "machine learning")),
    ("Analytics / BI", ("tableau", "power bi", "powerbi", "excel", "business intelligence")),
)

_GUIDANCE = {
    "MLOps / deployment": (["Official Docker and Kubernetes tutorials (free)", "MLflow documentation quickstarts (free)"], "Ship one model as a container with tracked experiments and a reproducible deployment."),
    "Data engineering": (["Apache Spark and Airflow official tutorials (free)"], "Build a tested batch pipeline from raw data to an analytics-ready table."),
    "Cloud platforms": (["AWS, Azure, or Google Cloud official free learning paths"], "Deploy a small data service on one cloud using an infrastructure diagram and cost notes."),
    "Machine learning": (["scikit-learn and PyTorch official tutorials (free)"], "Publish an evaluated model with baselines, error analysis, and reproducible training."),
    "Analytics / BI": (["Microsoft Learn or Tableau Public training (free)"], "Create a decision-focused dashboard with documented metric definitions."),
    "FRENCH_REQUIRED": (["TV5MONDE and RFI French learning materials (free)"], "Add a bilingual project summary only after the language level is genuinely supported."),
    "SENIORITY_MISMATCH": (["Open-source maintainer guides and system-design primers (free)"], "Own an end-to-end project with architecture decisions, tests, operations, and a postmortem."),
    "SPONSORSHIP_GATED": (["Official France/EU work-authorization guidance (free)"], "This is an eligibility gap, not a portfolio gap; target roles compatible with verified authorization."),
    "SALARY_BELOW_PREFERENCE": (["Public salary datasets and official labour-market statistics (free)"], "Document target-market salary evidence rather than changing a technical project."),
}


@dataclass(frozen=True)
class GapEvidence:
    job_id: str
    component: str
    score_impact: float


@dataclass(frozen=True)
class GapCluster:
    name: str
    evidence: list[GapEvidence]
    market_share_pct: float
    what_to_learn: list[str]
    project_suggestion: str
    simulated_score_lift: SimulatedScoreLift


@dataclass(frozen=True)
class GapReport:
    threshold: int
    scored_job_count: int
    low_score_job_count: int
    clusters: list[GapCluster]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class _ClusterState:
    evidence: list[GapEvidence] = field(default_factory=list)
    skills: set[str] = field(default_factory=set)
    jobs: dict[str, JobListing] = field(default_factory=dict)


def build_gap_report(
    db: Database,
    profile: CandidateProfile,
    evidence_store: EvidenceStore,
    *,
    threshold: int = 70,
    top: int | None = None,
) -> GapReport:
    """Aggregate deterministic score and ATS misses for all scored jobs below ``threshold``."""
    if not 0 <= threshold <= 100:
        raise ValueError("threshold must be between 0 and 100")
    if top is not None and top < 1:
        raise ValueError("top must be at least 1")
    scored = [job for job in db.list_jobs(limit=None) if job.fit_score is not None]
    low = sorted(
        (job for job in scored if job.fit_score is not None and job.fit_score < threshold),
        key=lambda item: item.id,
    )
    states: dict[str, _ClusterState] = {}
    for job in low:
        _collect_job_gaps(states, job, profile, evidence_store)
    clusters = [_build_cluster(name, state, len(low), profile) for name, state in states.items()]
    clusters.sort(key=lambda row: (-sum(item.score_impact for item in row.evidence), -len({item.job_id for item in row.evidence}), row.name.casefold()))
    if top is not None:
        clusters = clusters[:top]
    return GapReport(threshold, len(scored), len(low), clusters)


def write_gap_report(report: GapReport, path: Path) -> None:
    """Write a deterministic UTF-8 JSON artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _collect_job_gaps(
    states: dict[str, _ClusterState],
    job: JobListing,
    profile: CandidateProfile,
    evidence_store: EvidenceStore,
) -> None:
    explanation = explain_score(job, profile)
    breakdown = score_job(job, profile)
    skill_component = next(row for row in explanation["components"] if row["name"] == "skill")
    missing = list(explanation["missing_requirements"])
    per_skill = round(max(0.0, 100.0 - float(skill_component["score"])) * float(skill_component["weight"]) / max(1, len(missing)), 2)
    seen = {_normalise(skill) for skill in missing}
    for skill in missing:
        _add(states, _skill_family(skill), job, f"skill:{skill}", per_skill, skill)
    ats_gap = compute_ats_gap(job, profile, evidence_store)
    for skill in ats_gap.unsafe_claims_to_avoid:
        if _normalise(skill) not in seen:
            _add(states, _skill_family(skill), job, f"ats_gap:{skill}", 0.0, skill)
    for flag in breakdown.risk_flags:
        _add(states, flag, job, f"penalty:{flag}", _penalty_impact(flag, explanation), None)


def _add(states: dict[str, _ClusterState], name: str, job: JobListing, component: str, impact: float, skill: str | None) -> None:
    state = states.setdefault(name, _ClusterState())
    state.evidence.append(GapEvidence(job.id, component, impact))
    state.jobs[job.id] = job
    if skill:
        state.skills.add(skill)


def _build_cluster(name: str, state: _ClusterState, total: int, profile: CandidateProfile) -> GapCluster:
    resources, project = _GUIDANCE.get(name, (["Official documentation and community tutorials for this skill (free)"], "Build a small, tested artifact that demonstrates this skill in a realistic workflow."))
    share = round(len(state.jobs) / total * 100, 2) if total else 0.0
    simulation = simulate_score_lift(name, state.skills, list(state.jobs.values()), profile)
    evidence = sorted(state.evidence, key=lambda row: (row.job_id, row.component.casefold()))
    return GapCluster(name, evidence, share, list(resources), project, simulation)


def _skill_family(skill: str) -> str:
    normalised = _normalise(skill)
    for name, terms in _SKILL_FAMILIES:
        if any(term in normalised for term in terms):
            return name
    return f"Skill: {skill.strip()}"


def _penalty_impact(flag: str, explanation: dict[str, object]) -> float:
    components = explanation["components"]
    assert isinstance(components, list)
    component_name = {"SENIORITY_MISMATCH": "seniority", "SALARY_BELOW_PREFERENCE": "salary"}.get(flag)
    if component_name:
        row = next(item for item in components if item["name"] == component_name)
        return round((100.0 - float(row["score"])) * float(row["weight"]), 2)
    pre_cap = sum(float(item["contribution"]) for item in components)
    total_score = cast(int | float, explanation["total_score"])
    return round(max(0.0, pre_cap - float(total_score)), 2)


def _normalise(value: str) -> str:
    return " ".join(value.casefold().replace("-", " ").split())
