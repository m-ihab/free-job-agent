"""Hermetic HTTP coverage for the read-only Career Engine dashboard routes."""

from __future__ import annotations

import http.client
import json
import os
import threading
from contextlib import closing
from pathlib import Path

import pytest

from job_agent.db.database import Database
from job_agent.schemas.candidate import (
    CandidateProfile,
    ContactInfo,
    MasterCV,
    Project,
    QAProfile,
    Skill,
)
from job_agent.schemas.job import JobListing


@pytest.fixture
def career_server(tmp_path, monkeypatch, server_ready):
    """Serve synthetic profile/job data from an isolated dashboard instance."""
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True)
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(profiles_dir))

    profile = CandidateProfile(
        contact=ContactInfo(name="Synthetic Candidate", email="synthetic@example.test"),
        skills=[Skill(name="Python"), Skill(name="SQL")],
        target_roles=["Data Scientist", "ML Engineer"],
    )
    master_cv = MasterCV(
        contact=profile.contact,
        skills=profile.skills,
        projects=[
            Project(
                name="Synthetic Production System",
                description="Production system serving 250 synthetic requests per second.",
                technologies=["Python", "Docker"],
            )
        ],
    )
    (profiles_dir / "candidate_profile.json").write_text(profile.json(), encoding="utf-8")
    (profiles_dir / "master_cv.json").write_text(master_cv.json(), encoding="utf-8")
    (profiles_dir / "master_qa_profile.json").write_text(QAProfile().json(), encoding="utf-8")

    db = Database(data_dir / "jobs.db")
    db.initialize()
    job = JobListing(
        id="synthetic-career-job",
        title="ML Engineer",
        company="Synthetic Co",
        description="English-speaking role.",
        requirements=["Required: Python, Docker, MLflow, AWS"],
        tech_stack=["Python", "Docker", "MLflow", "AWS"],
    )
    job.fit_score = 45
    db.save_job(job)

    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, configured_app())
    port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    server_ready("127.0.0.1", port)
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(port: int, path: str) -> tuple[int, dict[str, object]]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", path)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
    return response.status, json.loads(raw)


def test_gap_report_route_honors_threshold_and_exposes_simulation(career_server: int) -> None:
    status, payload = _get(career_server, "/api/career/gap-report?threshold=80")

    assert status == 200
    assert payload["threshold"] == 80
    assert payload["scored_job_count"] == 1
    assert payload["low_score_job_count"] == 1
    clusters = payload["clusters"]
    assert isinstance(clusters, list) and clusters
    assert clusters[0]["simulated_score_lift"]["label"] == "simulated"


def test_cert_plan_route_returns_ranked_issuer_and_signal(career_server: int) -> None:
    status, payload = _get(career_server, "/api/career/cert-plan")

    assert status == 200
    recommendations = payload["recommendations"]
    assert isinstance(recommendations, list) and recommendations
    first = recommendations[0]
    assert first["certification"]["issuer"]
    assert first["signal_per_hour"] > 0
    assert first["matched_gaps"]


def test_project_plan_route_returns_audit_and_masterplan(career_server: int) -> None:
    status, payload = _get(career_server, "/api/career/project-plan")

    assert status == 200
    assert payload["project_verdicts"][0]["name"] == "Synthetic Production System"
    assert payload["project_verdicts"][0]["verdict"] == "signal"
    assert len(payload["masterplan"]) == 5
    assert payload["masterplan"][0]["hard_part"]


def test_career_get_routes_do_not_mutate_local_state(career_server: int) -> None:
    db = Database(Path(os.environ["JOB_AGENT_DATA_DIR"]) / "jobs.db")
    before = (len(db.list_jobs(limit=None)), db.list_evidence_items(), db.list_packets())

    for path in (
        "/api/career/gap-report",
        "/api/career/cert-plan",
        "/api/career/project-plan",
    ):
        status, _payload = _get(career_server, path)
        assert status == 200

    after = (len(db.list_jobs(limit=None)), db.list_evidence_items(), db.list_packets())
    assert after == before


@pytest.mark.parametrize("threshold", ["not-a-number", "-1", "101"])
def test_gap_report_route_rejects_invalid_threshold(
    career_server: int, threshold: str
) -> None:
    status, payload = _get(
        career_server, f"/api/career/gap-report?threshold={threshold}"
    )

    assert status == 400
    assert "threshold" in str(payload["error"]).lower()
