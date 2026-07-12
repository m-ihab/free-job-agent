"""Synthetic-only coverage for the local Career Engine gap coach."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from job_agent.career.gap_coach import build_gap_report, write_gap_report
from job_agent.cli.main import app
from job_agent.db.database import Database
from job_agent.evidence import EvidenceItem, EvidenceStore
from job_agent.schemas.candidate import (
    CandidateProfile,
    ContactInfo,
    MasterCV,
    QAProfile,
    Skill,
)
from job_agent.schemas.job import JobListing
from job_agent.scorer import score_job


@pytest.fixture
def profile() -> CandidateProfile:
    return CandidateProfile(
        contact=ContactInfo(name="Synthetic Candidate", email="synthetic@example.test"),
        skills=[Skill(name="Python")],
        languages=["English"],
        target_roles=["Data Scientist"],
        target_locations=["Paris"],
        work_authorizations=["EU citizen"],
    )


@pytest.fixture
def evidence(tmp_db: Database) -> EvidenceStore:
    return EvidenceStore(
        tmp_db,
        [EvidenceItem("skill", "Python", "synthetic fixture", "test")],
    )


def _job(job_id: str, skills: list[str], *, french: bool = False) -> JobListing:
    description = "French required." if french else "English-speaking role."
    return JobListing(
        id=job_id,
        title="Data Scientist",
        company="Synthetic Co",
        location="Paris",
        description=description,
        requirements=[f"Required: {', '.join(skills)}"],
        tech_stack=skills,
        languages=["french"] if french else [],
    )


def _save_scored(db: Database, job: JobListing, profile: CandidateProfile) -> None:
    job.fit_score = score_job(job, profile).total_score
    db.save_job(job)


def test_empty_database_returns_clean_empty_report(
    tmp_db: Database, profile: CandidateProfile, evidence: EvidenceStore
) -> None:
    report = build_gap_report(tmp_db, profile, evidence)

    assert report.scored_job_count == 0
    assert report.low_score_job_count == 0
    assert report.clusters == []


def test_jobs_at_or_above_threshold_are_excluded(
    tmp_db: Database, profile: CandidateProfile, evidence: EvidenceStore
) -> None:
    job = _job("above-threshold", ["Python"])
    job.fit_score = 70
    tmp_db.save_job(job)

    report = build_gap_report(tmp_db, profile, evidence, threshold=70)

    assert report.scored_job_count == 1
    assert report.low_score_job_count == 0
    assert report.clusters == []


def test_missing_skills_cluster_by_frequency_weighted_impact(
    tmp_db: Database, profile: CandidateProfile, evidence: EvidenceStore
) -> None:
    _save_scored(tmp_db, _job("mlops-1", ["Python", "Docker", "Kubernetes"]), profile)
    _save_scored(tmp_db, _job("mlops-2", ["Python", "Docker", "MLflow"]), profile)
    _save_scored(tmp_db, _job("data-eng-1", ["Python", "Spark", "Airflow"]), profile)

    report = build_gap_report(tmp_db, profile, evidence)

    assert report.clusters[0].name == "MLOps / deployment"
    assert {row.job_id for row in report.clusters[0].evidence} == {"mlops-1", "mlops-2"}
    skill_receipts = [row for row in report.clusters[0].evidence if row.component.startswith("skill:")]
    assert {row.job_id for row in skill_receipts} == {"mlops-1", "mlops-2"}
    assert report.clusters[0].market_share_pct == pytest.approx(66.67)


def test_french_penalty_cluster_is_detected(
    tmp_db: Database, profile: CandidateProfile, evidence: EvidenceStore
) -> None:
    _save_scored(tmp_db, _job("french-role", ["Python"], french=True), profile)

    report = build_gap_report(tmp_db, profile, evidence)
    cluster = next(row for row in report.clusters if row.name == "FRENCH_REQUIRED")

    assert cluster.evidence[0].job_id == "french-role"
    assert cluster.evidence[0].component == "penalty:FRENCH_REQUIRED"


def test_simulated_lift_uses_real_scorer_and_is_labeled(
    tmp_db: Database, profile: CandidateProfile, evidence: EvidenceStore
) -> None:
    job = _job("docker-role", ["Python", "Docker"])
    _save_scored(tmp_db, job, profile)

    cluster = build_gap_report(tmp_db, profile, evidence, threshold=80).clusters[0]
    simulated_profile = profile.copy(deep=True)
    simulated_profile.skills.append(Skill(name="Docker"))
    expected_after = score_job(job, simulated_profile).total_score

    assert cluster.simulated_score_lift.label == "simulated"
    assert cluster.simulated_score_lift.per_job[0].after_score == expected_after
    assert cluster.simulated_score_lift.per_job[0].lift == expected_after - score_job(job, profile).total_score


def test_json_artifact_round_trips(
    tmp_path, tmp_db: Database, profile: CandidateProfile, evidence: EvidenceStore
) -> None:
    _save_scored(tmp_db, _job("json-role", ["Python", "Docker", "MLflow"]), profile)
    report = build_gap_report(tmp_db, profile, evidence)
    output = tmp_path / "gap-report.json"

    write_gap_report(report, output)

    assert json.loads(output.read_text(encoding="utf-8")) == report.to_dict()


def test_gap_report_cli_registers_and_runs(tmp_path, monkeypatch, profile: CandidateProfile) -> None:
    data_dir = tmp_path / "data"
    profiles_dir = data_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(profiles_dir))
    (profiles_dir / "candidate_profile.json").write_text(profile.json(), encoding="utf-8")
    master_cv = MasterCV(contact=profile.contact, skills=profile.skills)
    (profiles_dir / "master_cv.json").write_text(master_cv.json(), encoding="utf-8")
    (profiles_dir / "master_qa_profile.json").write_text(QAProfile().json(), encoding="utf-8")
    db = Database(data_dir / "jobs.db")
    db.initialize()
    _save_scored(db, _job("cli-role", ["Python", "Docker", "MLflow"]), profile)
    output = tmp_path / "cli-gap.json"

    result = CliRunner().invoke(
        app, ["gap-report", "--threshold", "70", "--top", "3", "--json", str(output)]
    )

    assert result.exit_code == 0, result.exception
    assert "Gap report" in result.output
    assert "MLOps / deployment" in result.output
    assert "Receipts" in result.output
    assert json.loads(output.read_text(encoding="utf-8"))["clusters"]
