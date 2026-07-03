"""Behavioural tests for the profile-facts editor routes (local-only)."""
from __future__ import annotations

import http.client
import json
import re
import shutil
import threading
from contextlib import closing
from pathlib import Path

import pytest

from job_agent.ui.security import TOKEN_HEADER

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.fixture
def server(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    profiles_dir = data_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        shutil.copyfile(EXAMPLES_DIR / name, profiles_dir / name)
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(profiles_dir))

    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, configured_app())
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, _token(port), profiles_dir
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


def _post(port: int, token: str, path: str, body: dict) -> tuple[int, dict]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=10)) as conn:
        conn.request("POST", path, body=json.dumps(body).encode("utf-8"), headers={
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{port}",
            TOKEN_HEADER: token,
        })
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
    return resp.status, (json.loads(raw) if raw else {})


def _get(port: int, path: str) -> tuple[int, dict]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=10)) as conn:
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
    return resp.status, (json.loads(raw) if raw else {})


def test_get_profile_facts_returns_parsed_profile(server):
    port, _token_value, _profiles = server
    status, body = _get(port, "/api/profile-facts")
    assert status == 200
    assert body["profile"]["contact"]["name"]
    assert "target_roles" in body["profile"]


def test_post_profile_facts_saves_and_backs_up(server):
    port, token, profiles_dir = server
    status, body = _get(port, "/api/profile-facts")
    profile = body["profile"]
    profile["target_roles"] = ["Data Scientist", "ML Engineer"]
    profile["salary_min"] = 38000

    status, body = _post(port, token, "/api/profile-facts", {"profile": profile})
    assert status == 200
    assert body["ok"] is True

    saved = json.loads((profiles_dir / "candidate_profile.json").read_text(encoding="utf-8"))
    assert saved["target_roles"] == ["Data Scientist", "ML Engineer"]
    assert saved["salary_min"] == 38000
    backups = list(profiles_dir.glob("candidate_profile.*.bak"))
    assert backups, "a timestamped backup must be written before saving"


def test_post_profile_facts_rejects_invalid_schema(server):
    port, token, profiles_dir = server
    original = (profiles_dir / "candidate_profile.json").read_text(encoding="utf-8")
    status, body = _post(port, token, "/api/profile-facts", {"profile": {
        "contact": {"name": "X", "email": "x@y.z"},
        "salary_min": 90000,
        "salary_max": 10000,  # invalid: min > max
    }})
    assert status == 400
    assert "error" in body
    # File untouched on validation failure.
    assert (profiles_dir / "candidate_profile.json").read_text(encoding="utf-8") == original


def test_post_profile_facts_rejects_unknown_fields(server):
    port, token, _profiles = server
    status, _body = _post(port, token, "/api/profile-facts", {"profile": {
        "contact": {"name": "X", "email": "x@y.z"},
        "made_up_field": True,
    }})
    assert status == 400


def test_post_profile_facts_requires_profile_payload(server):
    port, token, _profiles = server
    status, _body = _post(port, token, "/api/profile-facts", {})
    assert status == 400
