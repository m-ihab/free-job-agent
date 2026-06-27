"""Dashboard preflight route behaviour."""
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
    job = JobListing(title="Stage Data Scientist", company="ACME", location="Paris", source="paste")
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


class _Result:
    def to_dict(self) -> dict[str, object]:
        return {"verdict": "APPLY", "fit_score": 91}


class _Evidence:
    def all(self) -> list[object]:
        return [object()]

    def rebuild(self, config) -> None:
        raise AssertionError("route should not rebuild a non-empty evidence cache")


def _token(port: int) -> str:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", "/")
        body = conn.getresponse().read().decode("utf-8")
    match = re.search(r'name="csrf-token" content="([^"]+)"', body)
    assert match, "token not injected into index.html"
    return match.group(1)


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


def test_preflight_route_requires_job_id(server):
    port, token, _job_id = server

    status, payload = _post(port, token, "/api/preflight", {})

    assert status == 400
    assert payload["error"] == "job_id is required."


def test_preflight_route_returns_preflight_payload(server, monkeypatch):
    from job_agent.ui.routes import post_preflight

    monkeypatch.setattr(post_preflight, "load_profile_bundle", lambda config: (object(), None, None))
    monkeypatch.setattr(post_preflight.EvidenceStore, "load", lambda config: _Evidence())
    monkeypatch.setattr(post_preflight, "run_preflight", lambda *args, **kwargs: _Result())
    port, token, job_id = server

    status, payload = _post(port, token, "/api/preflight", {"job_id": job_id})

    assert status == 200
    assert payload == {"preflight": {"verdict": "APPLY", "fit_score": 91}}
