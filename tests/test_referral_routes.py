"""Dashboard routes for contacts and referral warm paths."""
from __future__ import annotations

import http.client
import json
import re
import threading
from contextlib import closing

import pytest

from job_agent.schemas.job import JobListing
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
    job = JobListing(title="Data Scientist", company="DataCorp", location="Paris")
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


def test_contact_import_list_and_referral_routes(server):
    port, token, job_id = server

    import_status, imported = _post(
        port,
        token,
        "/api/contacts/import",
        {"contacts": [{"name": "Amina", "company": "DataCorp", "role": "ML Engineer", "relationship": "alumni"}]},
    )
    list_status, contacts = _get(port, "/api/contacts")
    match_status, matches = _get(port, f"/api/referrals?job_id={job_id}")
    ask_status, ask = _post(port, token, "/api/referral-ask", {"job_id": job_id, "contact_id": contacts["contacts"][0]["id"]})

    assert import_status == 200
    assert imported["imported"] == 1
    assert list_status == 200
    assert contacts["contacts"][0]["name"] == "Amina"
    assert match_status == 200
    assert matches["matches"][0]["contact"]["company"] == "DataCorp"
    assert ask_status == 200
    assert "Data Scientist" in ask["message"]
