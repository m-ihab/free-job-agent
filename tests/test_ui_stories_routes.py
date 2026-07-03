"""Behavioural tests for the story-bank and evaluation dashboard routes."""
from __future__ import annotations

import http.client
import json
import re
import shutil
import threading
from contextlib import closing
from pathlib import Path

import pytest

from job_agent.schemas.job import JobListing
from job_agent.ui.security import TOKEN_HEADER

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.fixture
def server(monkeypatch, tmp_path):
    """A live dashboard on a random port with seeded profiles and one job."""
    data_dir = tmp_path / "data"
    profiles_dir = data_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        shutil.copyfile(EXAMPLES_DIR / name, profiles_dir / name)
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(profiles_dir))

    from job_agent.db.database import Database
    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    config = configured_app()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = JobListing(title="Data Scientist", company="ACME", source="paste", raw_text="x",
                     tech_stack=["python"])
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
    assert match, "token not injected into index.html"
    return match.group(1)


def _post(port: int, token: str, path: str, body: dict) -> tuple[int, dict]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=10)) as conn:
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


def _get(port: int, path: str) -> tuple[int, dict]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=10)) as conn:
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
    return resp.status, (json.loads(raw) if raw else {})


def test_stories_crud_roundtrip(server):
    port, token, _job_id = server
    status, body = _get(port, "/api/stories")
    assert status == 200
    assert body["stories"] == []

    status, body = _post(port, token, "/api/story-save", {
        "title": "Churn model launch",
        "skills": ["python", "xgboost"],
        "situation": "S", "task": "T", "action": "A", "result": "R",
    })
    assert status == 200
    story_id = body["id"]

    status, body = _get(port, "/api/stories")
    assert status == 200
    assert len(body["stories"]) == 1
    assert body["stories"][0]["skills"] == ["python", "xgboost"]

    status, _ = _post(port, token, "/api/story-delete", {"id": story_id})
    assert status == 200
    assert _get(port, "/api/stories")[1]["stories"] == []


def test_story_save_requires_title(server):
    port, token, _job_id = server
    status, body = _post(port, token, "/api/story-save", {"situation": "no title"})
    assert status >= 400
    assert "title" in body.get("error", "").lower()


def test_story_sync_seeds_from_master_cv(server):
    port, token, _job_id = server
    status, body = _post(port, token, "/api/story-sync", {})
    assert status == 200
    assert body["added"] >= 1
    # Idempotent second sync.
    status, body = _post(port, token, "/api/story-sync", {})
    assert status == 200
    assert body["added"] == 0


def test_evaluate_returns_grade(server):
    port, token, job_id = server
    status, body = _post(port, token, "/api/evaluate", {"job_id": job_id})
    assert status == 200
    assert body["evaluation"]["overall_grade"] in {"A", "B", "C", "D", "F"}
    assert body["salary_context"]


def test_evaluate_validation_errors(server):
    port, token, _job_id = server
    status, _ = _post(port, token, "/api/evaluate", {})
    assert status >= 400
    status, _ = _post(port, token, "/api/evaluate", {"job_id": "does-not-exist"})
    assert status == 404


def test_discover_boards_route_uses_capped_company_list(server, monkeypatch):
    from job_agent.intake import discovery

    seen: dict = {}

    def _fake_discover(db, companies, **kwargs):
        seen["companies"] = companies
        return {"companies_checked": len(companies), "boards_found": 0, "boards": []}

    monkeypatch.setattr(discovery, "discover_boards", _fake_discover)
    port, token, _job_id = server
    status, body = _post(port, token, "/api/discover-boards",
                         {"companies": [f"Company {i}" for i in range(25)]})
    assert status == 200
    assert body["companies_checked"] == 10  # capped
    assert len(seen["companies"]) == 10


def test_company_boards_route_lists_saved_boards(server):
    port, token, _job_id = server
    status, body = _get(port, "/api/company-boards")
    assert status == 200
    assert body["boards"] == []
