"""Dashboard request guard: anti-CSRF (token + same-origin) and anti-DNS-rebind (Host)."""
from __future__ import annotations

import http.client
import re
import threading
from contextlib import closing

import pytest

from job_agent.ui.security import SESSION_TOKEN, TOKEN_HEADER, check_request


class _Headers:
    def __init__(self, data: dict) -> None:
        self._d = {k.lower(): v for k, v in data.items()}

    def get(self, key: str, default=None):
        return self._d.get(key.lower(), default)


class _Handler:
    def __init__(self, headers: dict) -> None:
        self.headers = _Headers(headers)


BOUND = {"bound_host": "127.0.0.1", "bound_port": 8765}


def test_same_origin_with_token_is_allowed() -> None:
    h = _Handler({
        "Host": "127.0.0.1:8765",
        "Origin": "http://127.0.0.1:8765",
        TOKEN_HEADER: SESSION_TOKEN,
    })
    assert check_request(h, "POST", **BOUND) == (True, "")


def test_cross_origin_post_is_blocked() -> None:
    h = _Handler({
        "Host": "127.0.0.1:8765",
        "Origin": "http://evil.example",
        TOKEN_HEADER: SESSION_TOKEN,
    })
    ok, reason = check_request(h, "POST", **BOUND)
    assert not ok and reason == "cross-origin"


def test_post_without_token_is_blocked() -> None:
    h = _Handler({"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"})
    ok, reason = check_request(h, "POST", **BOUND)
    assert not ok and reason == "missing-or-invalid-token"


def test_wrong_host_header_is_blocked() -> None:
    h = _Handler({
        "Host": "attacker.example:8765",
        "Origin": "http://127.0.0.1:8765",
        TOKEN_HEADER: SESSION_TOKEN,
    })
    ok, reason = check_request(h, "POST", **BOUND)
    assert not ok and reason == "host-not-allowed"


def test_get_is_not_token_gated() -> None:
    h = _Handler({"Host": "127.0.0.1:8765"})
    assert check_request(h, "GET", **BOUND) == (True, "")


# ── Integration: real server, guard fires before routing (no DB writes) ──────

@pytest.fixture
def live_server(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    server = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, configured_app())
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get_token(port: int) -> str:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", "/")
        body = conn.getresponse().read().decode("utf-8")
    match = re.search(r'name="csrf-token" content="([^"]+)"', body)
    assert match, "token not injected into index.html"
    return match.group(1)


def test_index_injects_token(live_server) -> None:
    assert _get_token(live_server)


def test_post_without_token_returns_403(live_server) -> None:
    with closing(http.client.HTTPConnection("127.0.0.1", live_server, timeout=5)) as conn:
        conn.request("POST", "/api/__guard_probe__", body=b"{}",
                     headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 403


def test_post_with_token_passes_guard(live_server) -> None:
    token = _get_token(live_server)
    with closing(http.client.HTTPConnection("127.0.0.1", live_server, timeout=5)) as conn:
        conn.request(
            "POST",
            "/api/__guard_probe__",
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{live_server}",
                TOKEN_HEADER: token,
            },
        )
        # Guard passes -> routing runs -> unknown route -> 404 (not 403).
        assert conn.getresponse().status == 404


def test_post_wrong_content_type_returns_415(live_server) -> None:
    token = _get_token(live_server)
    with closing(http.client.HTTPConnection("127.0.0.1", live_server, timeout=5)) as conn:
        conn.request(
            "POST",
            "/api/__guard_probe__",
            body=b"hello",
            headers={
                "Content-Type": "text/plain",
                "Origin": f"http://127.0.0.1:{live_server}",
                TOKEN_HEADER: token,
            },
        )
        assert conn.getresponse().status == 415
