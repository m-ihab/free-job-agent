"""Dashboard routes for the pipeline / conversion cockpit."""
from __future__ import annotations

import http.client
import json
import re
import threading
from contextlib import closing

import pytest

from job_agent.schemas.job import JobListing, JobStatus
from job_agent.ui.security import TOKEN_HEADER


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.db.database import Database
    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    config = configured_app()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = JobListing(
        title="Packet ready DS",
        company="ACME",
        location="Paris",
        status=JobStatus.PACKET_READY,
        fit_score=88,
    )
    db.save_job(job)

    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, configured_app())
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, _token(port), job.id
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _token(port: int) -> str:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", "/")
        body = conn.getresponse().read().decode("utf-8")
    match = re.search(r'name="csrf-token" content="([^"]+)"', body)
    assert match
    return match.group(1)


def _get(port: int, path: str) -> tuple[int, dict]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
    return resp.status, (json.loads(raw) if raw else {})


def _post(port: int, token: str, path: str, body: dict) -> tuple[int, dict]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request(
            "POST",
            path,
            body=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{port}",
                TOKEN_HEADER: token,
            },
        )
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
    return resp.status, (json.loads(raw) if raw else {})


def test_pipeline_today_and_metrics_routes(server):
    port, _token_value, _job_id = server

    status, today = _get(port, "/api/pipeline/today?limit=5")
    metrics_status, metrics = _get(port, "/api/pipeline/metrics")

    assert status == 200
    assert today["items"][0]["action"] == "Apply"
    assert metrics_status == 200
    assert metrics["stage_counts"]["PACKET_READY"] == 1


def test_next_action_and_notes_routes(server):
    port, token, job_id = server

    action_status, action = _post(port, token, "/api/next-action", {"job_id": job_id})
    notes_status, notes = _post(port, token, "/api/job-notes", {"job_id": job_id, "notes": "Contact alumni."})
    get_status, read_back = _get(port, f"/api/job-notes?job_id={job_id}")

    assert action_status == 200
    assert action["action"]["action"] == "Apply"
    assert notes_status == 200
    assert notes["notes"] == "Contact alumni."
    assert get_status == 200
    assert read_back["notes"] == "Contact alumni."
