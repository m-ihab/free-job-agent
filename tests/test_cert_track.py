"""Synthetic-only coverage for Career Engine certification planning."""

from __future__ import annotations

import json
from datetime import date

from click.testing import CliRunner

from job_agent.career.cert_track import (
    Certification,
    build_cert_plan,
    load_certification_catalog,
)
from job_agent.career.gap_coach import GapCluster, GapEvidence
from job_agent.career.gap_simulation import SimulatedScoreLift
from job_agent.cli.main import app
from job_agent.db.database import Database
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, MasterCV, QAProfile, Skill
from job_agent.schemas.job import JobListing
from job_agent.scorer import score_job


def _cluster(name: str, *components: str) -> GapCluster:
    return GapCluster(
        name=name,
        evidence=[GapEvidence("synthetic-job", component, 1.0) for component in components],
        market_share_pct=50.0,
        what_to_learn=[],
        project_suggestion="Synthetic project suggestion.",
        simulated_score_lift=SimulatedScoreLift("simulated", 0.0, []),
    )


def _cert(
    cert_id: str,
    *,
    hours: float,
    weight: int,
    tags: list[str],
) -> Certification:
    return Certification(
        id=cert_id,
        name=cert_id,
        issuer="Synthetic Issuer",
        cost="free",
        est_hours=hours,
        skill_tags=tags,
        recruiter_weight=weight,
        roles_it_moves=["Data Scientist"],
        checked_date=date(2026, 7, 13),
    )


def test_catalog_contains_prd_shortlist_with_current_check_date() -> None:
    catalog = load_certification_catalog()

    assert {item.issuer for item in catalog} == {
        "AWS Skill Builder",
        "Databricks",
        "DeepLearning.AI",
        "Google Cloud",
        "IBM SkillsBuild",
        "Kaggle",
        "Salesforce Trailhead",
    }
    assert all(item.checked_date == date(2026, 7, 13) for item in catalog)
    assert all(item.cost and item.est_hours > 0 for item in catalog)
    assert all(1 <= item.recruiter_weight <= 3 for item in catalog)
    assert all(item.roles_it_moves for item in catalog)


def test_rank_is_signal_per_hour_then_gap_coverage() -> None:
    gaps = [
        _cluster("MLOps / deployment", "skill:Docker"),
        _cluster("Cloud platforms", "skill:AWS"),
    ]
    catalog = [
        _cert("lower-ratio", hours=4, weight=1, tags=["MLOps / deployment", "Cloud platforms"]),
        _cert("tie-less-coverage", hours=4, weight=2, tags=["MLOps / deployment"]),
        _cert(
            "tie-more-coverage", hours=4, weight=2, tags=["MLOps / deployment", "Cloud platforms"]
        ),
        _cert("highest-ratio", hours=2, weight=2, tags=["Cloud platforms"]),
    ]

    plan = build_cert_plan(gaps, catalog=catalog, top=4, as_of=date(2026, 7, 13))

    assert [item.certification.id for item in plan.recommendations] == [
        "highest-ratio",
        "tie-more-coverage",
        "tie-less-coverage",
        "lower-ratio",
    ]
    assert plan.recommendations[0].signal_per_hour == 1.0
    assert plan.recommendations[1].gap_coverage == 2


def test_catalog_warning_appears_only_after_ninety_days() -> None:
    cert = _cert("aging", hours=2, weight=2, tags=["Cloud platforms"])
    gap = _cluster("Cloud platforms", "skill:GCP")

    fresh = build_cert_plan([gap], catalog=[cert], top=3, as_of=date(2026, 10, 11))
    stale = build_cert_plan([gap], catalog=[cert], top=3, as_of=date(2026, 10, 12))

    assert fresh.warnings == []
    assert stale.warnings and "aging" in stale.warnings[0]


def test_cert_plan_cli_uses_only_synthetic_profile_bundle(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    profiles_dir = data_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(profiles_dir))
    profile = CandidateProfile(
        contact=ContactInfo(name="Synthetic Candidate", email="synthetic@example.test"),
        skills=[Skill(name="Python")],
        target_roles=["Machine Learning Engineer"],
    )
    (profiles_dir / "candidate_profile.json").write_text(profile.json(), encoding="utf-8")
    (profiles_dir / "master_cv.json").write_text(
        MasterCV(contact=profile.contact, skills=profile.skills).json(), encoding="utf-8"
    )
    (profiles_dir / "master_qa_profile.json").write_text(QAProfile().json(), encoding="utf-8")
    db = Database(data_dir / "jobs.db")
    db.initialize()
    job = JobListing(
        id="synthetic-mlops",
        title="ML Engineer",
        company="Synthetic Co",
        description="English-speaking role.",
        requirements=["Required: Python, Docker, MLflow, AWS"],
        tech_stack=["Python", "Docker", "MLflow", "AWS"],
    )
    job.fit_score = score_job(job, profile).total_score
    db.save_job(job)
    output = tmp_path / "cert-plan.json"

    result = CliRunner().invoke(app, ["cert-plan", "--top", "5", "--json", str(output)])

    assert result.exit_code == 0, result.exception
    assert "Certification plan" in result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert 3 <= len(payload["recommendations"]) <= 5
    assert payload["recommendations"][0]["matched_gaps"]
