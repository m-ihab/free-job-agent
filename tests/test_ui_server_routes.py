"""Characterization tests for the dashboard HTTP routes.

These lock in the *observable* behaviour (status code + JSON shape) of a
representative set of GET/POST routes on ``JobAgentHandler`` so the WP-4
route-table refactor can be proven behaviour-preserving. They drive a real
loopback server with a seeded temp database; no network / LLM / browser calls.
"""
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
    """A live dashboard on a random port, seeded with two jobs.

    Yields ``(port, token, ids)`` where ``ids`` maps logical names to job ids.
    """
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.db.database import Database
    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    config = configured_app()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    saved = JobListing(title="Data Scientist", company="ACME", source="paste", raw_text="x")
    walled = JobListing(title="ML Engineer", company="Globex", source="paste", raw_text="y")
    db.save_job(saved)
    db.save_job(walled)
    db.update_job_status(walled.id, JobStatus.NEEDS_MANUAL)
    db.log_event(walled.id, "NEEDS_MANUAL", {"reason": "reCAPTCHA challenge"})

    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, configured_app())
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, _token(port), {"saved": saved.id, "walled": walled.id}
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _token(port: int) -> str:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", "/")
        body = conn.getresponse().read().decode("utf-8")
    match = re.search(r'name="csrf-token" content="([^"]+)"', body)
    assert match, "token not injected into index.html"
    return match.group(1)


def _get(port: int, path: str) -> tuple[int, dict]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
    try:
        return resp.status, json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return resp.status, {"_raw": raw}


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


# ── GET routes ───────────────────────────────────────────────────────────────

def test_get_state_returns_profile_sources_statuses(server):
    port, _, _ = server
    status, payload = _get(port, "/api/state")
    assert status == 200
    assert {"profile", "sources", "statuses", "app"} <= payload.keys()
    assert isinstance(payload["statuses"], list)


def test_get_jobs_lists_all_seeded_jobs(server):
    port, _, ids = server
    status, payload = _get(port, "/api/jobs")
    assert status == 200
    listed = {job["id"] for job in payload["jobs"]}
    assert {ids["saved"], ids["walled"]} <= listed


def test_get_jobs_filtered_by_status(server):
    port, _, ids = server
    status, payload = _get(port, "/api/jobs?status=NEEDS_MANUAL")
    assert status == 200
    assert [job["id"] for job in payload["jobs"]] == [ids["walled"]]


def test_get_needs_manual_carries_reason(server):
    port, _, ids = server
    status, payload = _get(port, "/api/needs-manual")
    assert status == 200
    assert [job["id"] for job in payload["jobs"]] == [ids["walled"]]
    assert payload["jobs"][0]["needs_manual_reason"] == "reCAPTCHA challenge"


def test_get_packets_empty_by_default(server):
    port, _, _ = server
    status, payload = _get(port, "/api/packets")
    assert status == 200
    assert payload == {"packets": []}


def test_get_autopilot_status_shape(server):
    port, _, _ = server
    status, payload = _get(port, "/api/autopilot")
    assert status == 200
    assert isinstance(payload, dict)


def test_get_auto_apply_status_shape(server):
    port, _, _ = server
    status, payload = _get(port, "/api/auto-apply/status")
    assert status == 200
    assert isinstance(payload, dict)


def test_unknown_route_is_404(server):
    port, _, _ = server
    status, _ = _get(port, "/api/does-not-exist")
    assert status == 404


# ── POST routes (mutating, guard-gated) ──────────────────────────────────────

def test_post_status_updates_job(server):
    port, token, ids = server
    status, payload = _post(port, token, "/api/status",
                            {"job_id": ids["saved"], "status": "MANUALLY_SUBMITTED"})
    assert status == 200 and payload == {"ok": True}
    _, jobs = _get(port, "/api/jobs?status=MANUALLY_SUBMITTED")
    assert ids["saved"] in {job["id"] for job in jobs["jobs"]}


def test_post_delete_job_removes_it(server):
    port, token, ids = server
    status, payload = _post(port, token, "/api/delete-job", {"job_id": ids["saved"]})
    assert status == 200 and payload["ok"] is True
    _, jobs = _get(port, "/api/jobs")
    assert ids["saved"] not in {job["id"] for job in jobs["jobs"]}


def test_post_add_url_rejects_ssrf_target(server):
    """The SSRF guard must reject a private/metadata URL through the route
    (no network is performed) — characterizes the F2 fix end-to-end."""
    port, token, _ = server
    status, payload = _post(port, token, "/api/add-url",
                            {"url": "http://169.254.169.254/latest/meta-data/"})
    assert status == 400
    assert "error" in payload


def test_post_add_url_rejects_file_scheme(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/add-url", {"url": "file:///etc/passwd"})
    assert status == 400
    assert "error" in payload


def _get_with_host(port: int, path: str, host: str) -> int:
    """GET with an explicit (possibly spoofed) Host header; returns status code."""
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host)
        conn.endheaders()
        return conn.getresponse().status


def test_get_rejects_spoofed_host(server):
    """DNS-rebinding defence: a GET whose Host is not in the loopback allowlist
    is refused, so a cross-origin page cannot read /api data via 127.0.0.1."""
    port, _, _ = server
    assert _get_with_host(port, "/api/jobs", "evil.attacker.example") == 403


def test_get_allows_loopback_host(server):
    port, _, _ = server
    assert _get_with_host(port, "/api/jobs", f"127.0.0.1:{port}") == 200
