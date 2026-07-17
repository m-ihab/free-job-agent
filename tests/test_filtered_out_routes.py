"""Hermetic HTTP coverage for the read-only filtered-out dashboard route."""

from __future__ import annotations

import http.client
import json
import os
import threading
import re
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from job_agent.db.database import Database
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, MasterCV, QAProfile
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.ui.security import TOKEN_HEADER


@pytest.fixture
def filtered_out_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    server_ready: Callable[[str, int], None],
) -> Iterator[int]:
    """Serve synthetic profile/job data from an isolated dashboard instance."""
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True)
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(profiles_dir))

    contact = ContactInfo(name="Synthetic Candidate", email="synthetic@example.test")
    profile = CandidateProfile(
        contact=contact,
        target_roles=["Data Scientist"],
        excluded_companies=["Blocked Synthetic Co"],
    )
    (profiles_dir / "candidate_profile.json").write_text(profile.json(), encoding="utf-8")
    (profiles_dir / "master_cv.json").write_text(
        MasterCV(contact=contact).json(), encoding="utf-8"
    )
    (profiles_dir / "master_qa_profile.json").write_text(
        QAProfile().json(), encoding="utf-8"
    )

    db = Database(data_dir / "jobs.db")
    db.initialize()
    for job in (
        JobListing(
            id="blocked-job",
            title="Data Scientist",
            company="Blocked Synthetic Co",
            description="Python and SQL analytics.",
            remote=True,
            status=JobStatus.FILTERED,
        ),
        JobListing(
            id="noise-job",
            title="Cancer Data Abstractor",
            company="Synthetic Registry",
            description="Cancer registry abstraction role.",
            remote=True,
            status=JobStatus.FILTERED,
        ),
        JobListing(
            id="passing-job",
            title="Data Scientist",
            company="Allowed Labs",
            description="Python, SQL, pandas, and machine learning.",
            remote=True,
        ),
    ):
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


def _get(port: int) -> tuple[int, dict[str, Any]]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", "/api/filtered-out")
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
    return response.status, json.loads(raw)


def _token(port: int) -> str:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", "/")
        body = conn.getresponse().read().decode("utf-8")
    match = re.search(r'name="csrf-token" content="([^"]+)"', body)
    assert match
    return match.group(1)


def _post(port: int, body: dict[str, str]) -> tuple[int, dict[str, Any]]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request(
            "POST",
            "/api/filtered-out/action",
            body=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{port}",
                TOKEN_HEADER: _token(port),
            },
        )
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
    return response.status, json.loads(raw)


def test_filtered_out_route_groups_existing_filter_and_noise_reasons(
    filtered_out_server: int,
) -> None:
    status, payload = _get(filtered_out_server)

    assert status == 200
    assert payload["evaluated_count"] == 3
    assert payload["filtered_count"] == 2
    assert payload["passed_count"] == 1
    assert payload["rule_counts"] == {
        "blocked_company": 1,
        "search_generic_data_title": 1,
        "search_off_topic_title": 1,
    }
    jobs = {job["id"]: job for job in payload["jobs"]}
    assert "Blocked company: Blocked Synthetic Co" in jobs["blocked-job"]["reason"]
    assert jobs["blocked-job"]["reasons"][0]["rule"] == "blocked_company"
    assert jobs["noise-job"]["reasons"] == [
        {"rule": "search_generic_data_title", "message": "Generic data title"},
        {"rule": "search_off_topic_title", "message": "Off-topic title"},
    ]


def test_filtered_out_route_does_not_mutate_local_state(filtered_out_server: int) -> None:
    db = Database(Path(os.environ["JOB_AGENT_DATA_DIR"]) / "jobs.db")
    before = (
        [(job.id, job.status, job.updated_at) for job in db.list_jobs(limit=None)],
        db.list_packets(),
        db.list_evidence_items(),
    )

    status, _payload = _get(filtered_out_server)

    assert status == 200
    after = (
        [(job.id, job.status, job.updated_at) for job in db.list_jobs(limit=None)],
        db.list_packets(),
        db.list_evidence_items(),
    )
    assert after == before


def test_filtered_out_restore_is_idempotent_and_requeues_job(
    filtered_out_server: int,
) -> None:
    first_status, first = _post(
        filtered_out_server, {"job_id": "blocked-job", "action": "restore"}
    )
    second_status, second = _post(
        filtered_out_server, {"job_id": "blocked-job", "action": "restore"}
    )

    assert first_status == second_status == 200
    assert first == {"ok": True, "action": "restore", "job_id": "blocked-job", "changed": True}
    assert second == {"ok": True, "action": "restore", "job_id": "blocked-job", "changed": False}
    db = Database(Path(os.environ["JOB_AGENT_DATA_DIR"]) / "jobs.db")
    assert db.get_job("blocked-job").status is JobStatus.NEW
    _status, payload = _get(filtered_out_server)
    assert "blocked-job" not in {job["id"] for job in payload["jobs"]}


def test_filtered_out_delete_uses_tracker_removal_path(filtered_out_server: int) -> None:
    status, payload = _post(
        filtered_out_server, {"job_id": "noise-job", "action": "delete"}
    )

    assert status == 200
    assert payload == {"ok": True, "action": "delete", "job_id": "noise-job"}
    db = Database(Path(os.environ["JOB_AGENT_DATA_DIR"]) / "jobs.db")
    assert db.get_job("noise-job") is None


def test_filtered_out_action_returns_404_for_unknown_job(filtered_out_server: int) -> None:
    status, payload = _post(
        filtered_out_server, {"job_id": "missing-job", "action": "restore"}
    )

    assert status == 404
    assert payload == {"error": "Job not found: missing-job"}
