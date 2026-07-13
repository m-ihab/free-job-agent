"""Synthetic-only coverage for the Career Engine project auditor."""

from __future__ import annotations

import json

from click.testing import CliRunner

from job_agent.career.gap_coach import GapCluster, GapEvidence
from job_agent.career.gap_simulation import SimulatedScoreLift
from job_agent.career.project_audit import build_project_audit
from job_agent.cli.main import app
from job_agent.db.database import Database
from job_agent.evidence import EvidenceStore, build_evidence_items
from job_agent.schemas.candidate import (
    CandidateProfile,
    ContactInfo,
    MasterCV,
    Project,
    QAProfile,
    Skill,
)
from job_agent.schemas.job import JobListing
from job_agent.scorer import score_job


def _cluster(name: str, component: str) -> GapCluster:
    return GapCluster(
        name=name,
        evidence=[GapEvidence("synthetic-job", component, 2.0)],
        market_share_pct=50.0,
        what_to_learn=[],
        project_suggestion="Synthetic project suggestion.",
        simulated_score_lift=SimulatedScoreLift("simulated", 0.0, []),
    )


def _profile() -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name="Synthetic Candidate", email="synthetic@example.test"),
        skills=[Skill(name="Python"), Skill(name="SQL")],
        target_roles=["Data Scientist", "ML Engineer"],
    )


def test_project_verdict_rules_are_deterministic(tmp_db: Database) -> None:
    profile = _profile()
    master_cv = MasterCV(
        contact=profile.contact,
        projects=[
            Project(
                name="Titanic Tutorial Clone",
                description="Copied walkthrough with 81% accuracy.",
                technologies=["Python", "scikit-learn"],
            ),
            Project(
                name="Customer Churn Study",
                description="Explores churn drivers without a measured outcome.",
                technologies=["Python", "SQL"],
            ),
            Project(
                name="Demand Forecasting",
                description="Reduced forecast error by 18% against a seasonal baseline.",
                technologies=["Python", "scikit-learn"],
            ),
            Project(
                name="Free Job Agent",
                description="Local-first production system with tested scoring and safe automation.",
                technologies=["Python", "SQLite", "Playwright"],
            ),
        ],
    )
    qa = QAProfile()
    evidence = EvidenceStore(tmp_db, build_evidence_items(profile, master_cv, qa))

    report = build_project_audit(
        profile,
        master_cv,
        evidence,
        [_cluster("MLOps / deployment", "skill:Docker")],
        top=4,
    )

    verdicts = {item.name: item for item in report.project_verdicts}
    assert verdicts["Titanic Tutorial Clone"].verdict == "dilutive"
    assert verdicts["Customer Churn Study"].verdict == "neutral"
    assert verdicts["Demand Forecasting"].verdict == "signal"
    assert verdicts["Free Job Agent"].verdict == "signal"
    assert verdicts["Free Job Agent"].strong_pattern == "fja-itself"
    assert verdicts["Demand Forecasting"].matched_target_stack
    assert all(item.evidence_receipts for item in report.project_verdicts)


def test_masterplan_has_four_to_six_specs_ranked_by_gap_coverage_visibility(
    tmp_db: Database,
) -> None:
    profile = _profile()
    master_cv = MasterCV(contact=profile.contact)
    evidence = EvidenceStore(tmp_db, build_evidence_items(profile, master_cv, QAProfile()))
    gaps = [
        _cluster("MLOps / deployment", "skill:Docker"),
        _cluster("Cloud platforms", "skill:AWS"),
        _cluster("Data engineering", "skill:Spark"),
    ]

    report = build_project_audit(profile, master_cv, evidence, gaps, top=6)

    assert len(report.masterplan) == 6
    assert [item.rank_score for item in report.masterplan] == sorted(
        (item.rank_score for item in report.masterplan), reverse=True
    )
    assert any("Free Job Agent" in item.name for item in report.masterplan)
    assert all(item.problem and item.dataset_suggestion for item in report.masterplan)
    assert all(item.stack and item.hard_part and item.deliverable for item in report.masterplan)
    assert all(
        item.readme_demo_requirements and item.time_budget_h > 0 for item in report.masterplan
    )
    assert report.verdict_rules


def test_project_plan_cli_uses_gap_coach_loading_path(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    profiles_dir = data_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(profiles_dir))
    profile = _profile()
    project = Project(
        name="Synthetic Production System",
        description="Production system serving 250 synthetic requests per second.",
        technologies=["Python", "Docker"],
    )
    master_cv = MasterCV(contact=profile.contact, skills=profile.skills, projects=[project])
    (profiles_dir / "candidate_profile.json").write_text(profile.json(), encoding="utf-8")
    (profiles_dir / "master_cv.json").write_text(master_cv.json(), encoding="utf-8")
    (profiles_dir / "master_qa_profile.json").write_text(QAProfile().json(), encoding="utf-8")
    db = Database(data_dir / "jobs.db")
    db.initialize()
    job = JobListing(
        id="synthetic-data-role",
        title="Data Scientist",
        company="Synthetic Co",
        description="English-speaking role.",
        requirements=["Required: Python, Docker, Spark"],
        tech_stack=["Python", "Docker", "Spark"],
    )
    job.fit_score = score_job(job, profile).total_score
    db.save_job(job)
    output = tmp_path / "project-plan.json"

    result = CliRunner().invoke(app, ["project-plan", "--top", "5", "--json", str(output)])

    assert result.exit_code == 0, result.exception
    assert "Project audit" in result.output
    assert "Project masterplan" in result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["masterplan"]) == 5
    assert payload["project_verdicts"][0]["verdict"] == "signal"
