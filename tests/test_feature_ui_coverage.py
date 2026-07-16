"""Coverage contract for CLI features surfaced by the local dashboard."""
from __future__ import annotations

import argparse
import base64
import http.client
import json
import re
import threading
from contextlib import closing
from pathlib import Path

import pytest

from job_agent.cli.main import LocalCLIApp
from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.ui.security import TOKEN_HEADER

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "job_agent" / "ui" / "static"


def _leaf_commands(
    parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()
) -> set[str]:
    commands: set[str] = set()
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, child in action.choices.items():
            nested = _leaf_commands(child, (*prefix, name))
            commands.update(nested or {" ".join((*prefix, name))})
    return commands


def test_palette_catalogs_every_argparse_leaf_command() -> None:
    source = "\n".join(
        (STATIC / name).read_text(encoding="utf-8")
        for name in ("feature_catalog.js", "palette.js")
    )
    cataloged = set(re.findall(r'command:\s*"([^"]+)"', source))

    assert cataloged == _leaf_commands(LocalCLIApp().build_parser())
    assert 'kind: "CLI only"' in source
    assert "All features" in source


def test_missing_feature_controls_are_visible_and_route_backed() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = "\n".join(path.read_text(encoding="utf-8") for path in STATIC.glob("*.js"))

    for control in (
        'id="profileImportFile"',
        'id="profileImportBtn"',
        'id="franceTargetsBtn"',
        'id="franceTargetsResults"',
        'id="drawerHistory"',
    ):
        assert control in html
    for route in ("/api/profile-import", "/api/france-targets", "/api/job-history"):
        assert route in scripts


@pytest.fixture
def feature_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server_ready):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    db = Database(data_dir / "jobs.db")
    db.initialize()
    job = JobListing(
        id="feature-job", title="Data Scientist", company="Example", description="Python"
    )
    db.save_job(job)
    db.log_event(job.id, "STATUS_CHANGED", {"status": JobStatus.SCORED.value})

    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, configured_app())
    port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    server_ready("127.0.0.1", port)
    try:
        yield port, _token(port), db
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _token(port: int) -> str:
    status, body = _request(port, "GET", "/")
    assert status == 200
    match = re.search(r'name="csrf-token" content="([^"]+)"', body)
    assert match
    return match.group(1)


def _request(
    port: int,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
    token: str = "",
) -> tuple[int, str]:
    headers: dict[str, str] = {}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{port}",
            TOKEN_HEADER: token,
        }
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        return response.status, response.read().decode("utf-8")


def test_profile_import_route_reuses_grounded_evidence_import(feature_server) -> None:
    port, token, db = feature_server
    resume = {"basics": {"name": "Ada Example"}, "skills": [{"name": "Python"}]}
    encoded = base64.b64encode(json.dumps(resume).encode("utf-8")).decode("ascii")

    status, raw = _request(
        port,
        "POST",
        "/api/profile-import",
        {"filename": "resume.json", "content_base64": encoded},
        token,
    )

    payload = json.loads(raw)
    assert status == 200
    assert payload["parsed"] == 2
    assert payload["stored"] == 2
    stored = db.list_evidence_items()
    assert len(stored) == 2
    assert {item["source"] for item in stored} == {"resume.json"}


@pytest.mark.parametrize(
    ("filename", "content"),
    [("resume.txt", "e30="), ("resume.json", "not-base64")],
)
def test_profile_import_route_rejects_unsafe_uploads(
    feature_server, filename: str, content: str
) -> None:
    port, token, db = feature_server

    status, raw = _request(
        port,
        "POST",
        "/api/profile-import",
        {"filename": filename, "content_base64": content},
        token,
    )

    assert status == 400
    assert json.loads(raw)["error"]
    assert db.list_evidence_items() == []


def test_france_targets_and_job_history_routes(feature_server) -> None:
    port, _token_value, _db = feature_server

    targets_status, targets_raw = _request(port, "GET", "/api/france-targets?limit=3")
    history_status, history_raw = _request(
        port, "GET", "/api/job-history?job_id=feature-job"
    )

    targets = json.loads(targets_raw)
    history = json.loads(history_raw)
    assert targets_status == history_status == 200
    assert len(targets["targets"]) == 3
    assert set(targets["targets"][0]) == {"company", "sector", "url"}
    assert history["events"][0]["event_type"] == "STATUS_CHANGED"
