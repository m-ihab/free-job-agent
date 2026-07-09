"""Dashboard /api/score-explain route behaviour (G2 frontend backend seam)."""
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
PROFILE_FILES = ("candidate_profile.json", "master_cv.json", "master_qa_profile.json")


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    # Hermetic profiles: seed the isolated dir with the tracked examples and pin
    # JOB_AGENT_PROFILES_DIR, so load_profile_bundle never falls back to a real
    # profiles/ dir on the developer machine (present locally, absent in CI).
    profiles_dir = tmp_path / "data" / "profiles"
    profiles_dir.mkdir(parents=True)
    for name in PROFILE_FILES:
        shutil.copy(EXAMPLES_DIR / name, profiles_dir / name)
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(profiles_dir))
    from job_agent.db.database import Database
    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    config = configured_app()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = JobListing(
        title="Data Scientist", company="ACME", location="Paris", source="paste",
        tech_stack=["python", "sql"],
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


def test_score_explain_requires_job_id(server):
    port, token, _job_id = server

    status, payload = _post(port, token, "/api/score-explain", {})

    assert status == 400
    assert payload["error"] == "job_id is required."


def test_score_explain_unknown_job(server):
    port, token, _job_id = server

    status, payload = _post(port, token, "/api/score-explain", {"job_id": "nope"})

    assert status == 400
    assert payload["error"] == "Job not found."


def test_score_explain_returns_decomposition(server, monkeypatch):
    from job_agent.ui.routes import post_score_explain as route

    # Patch on the route module (patch where it's looked up — G-3).
    class _Profile:
        pass

    monkeypatch.setattr(route, "load_profile_bundle", lambda config: (_Profile(), None, None))
    monkeypatch.setattr(
        route, "explain_score",
        lambda job, profile, *, semantic_score=None: {
            "job_id": job.id,
            "components": [
                {"name": "skill", "score": 80, "weight": 0.35, "contribution": 28.0},
            ],
            "caps_applied": [],
            "total_score": 74,
            "decision": "APPLY",
            "confidence": 0.8,
            "missing_requirements": [],
            "notes": [],
        },
    )
    port, token, job_id = server

    status, payload = _post(port, token, "/api/score-explain", {"job_id": job_id})

    assert status == 200
    assert payload["explain"]["total_score"] == 74
    assert payload["explain"]["components"][0]["name"] == "skill"
    assert payload["job"]["company"] == "ACME"


def test_score_explain_survives_embedding_failure(server, monkeypatch):
    """The drawer must still explain deterministic components when the local
    embedding model is unavailable (fail-soft, same policy as the pipeline)."""
    from job_agent.ui.routes import post_score_explain as route

    def _boom(job, profile, db):
        raise RuntimeError("no embedding model")

    monkeypatch.setattr(route.embeddings, "semantic_similarity", _boom)
    port, token, job_id = server

    status, payload = _post(port, token, "/api/score-explain", {"job_id": job_id})

    assert status == 200
    assert "components" in payload["explain"]
    names = {c["name"] for c in payload["explain"]["components"]}
    assert "semantic" not in names  # semantic component absent, not fabricated
