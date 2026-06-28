"""Dashboard cover-letter on-demand route."""
from __future__ import annotations

import http.client
import json
import re
import threading
from contextlib import closing
from types import SimpleNamespace

import pytest

from job_agent.schemas.packet import PacketStatus
from job_agent.ui.security import TOKEN_HEADER


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, configured_app())
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, _token(port)
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


def test_cover_letter_route_requires_job_id(server):
    port, token = server

    status, payload = _post(port, token, "/api/cover-letter", {})

    assert status == 400
    assert "job_id" in payload["error"]


def test_cover_letter_route_returns_packet_payload(server, monkeypatch):
    from job_agent.ui.routes import post_cover_letter

    packet = SimpleNamespace(
        id="pkt_1",
        job_id="job_1",
        status=PacketStatus.READY,
        fit_score=80,
        fit_decision="good",
        headline="",
        summary="",
        keywords=[],
        tailored_cv_pdf_path="",
        cover_letter_pdf_path="C:/tmp/cover_letter.pdf",
        artifacts=[],
    )
    monkeypatch.setattr(post_cover_letter, "generate_cover_letter_on_demand", lambda config, job_id: packet)
    port, token = server

    status, payload = _post(port, token, "/api/cover-letter", {"job_id": "job_1"})

    assert status == 200
    assert payload["packet"]["id"] == "pkt_1"
    assert payload["packet"]["cover_letter_pdf"] == "C:/tmp/cover_letter.pdf"
