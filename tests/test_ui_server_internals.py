"""Behavioural tests for ``job_agent.ui.server`` internals + get_portfolio.

Covers the parts the route-level tests do not reach:
- ``run_server`` / ``main`` argument parsing and the non-loopback bind guard
  (asserted by catching ``SystemExit`` *before* any socket is bound),
- the static-serving helpers ``_send_static`` / ``_send_file`` / ``_send_index``
  (token injection + path-containment branches) driven through a fake socket,
- the portfolio GET handlers (preview inlines CSS, style.css, asset 404).

No real non-loopback bind is ever performed and no LaTeX/LLM/network runs.
"""
from __future__ import annotations

import http.client
import io
import json
import threading
from contextlib import closing

import pytest

from job_agent.config import AppConfig
from job_agent.ui import server as server_mod
from job_agent.ui.server import JobAgentHandler


# --------------------------------------------------------------------------- #
# A handler instance wired to a fake socket so we can call methods directly.   #
# --------------------------------------------------------------------------- #


class _FakeServer:
    def __init__(self, config: AppConfig):
        self.config = config
        self.server_address = ("127.0.0.1", 0)


def _make_handler(config: AppConfig) -> JobAgentHandler:
    handler = JobAgentHandler.__new__(JobAgentHandler)
    handler.server = _FakeServer(config)  # type: ignore[attr-defined]
    handler.wfile = io.BytesIO()
    handler.rfile = io.BytesIO()
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET / HTTP/1.1"
    handler.command = "GET"
    handler.client_address = ("127.0.0.1", 12345)

    # Stub the response-writing machinery so methods can run without a socket.
    def _send_response(code, message=None):
        handler.wfile.write(f"HTTP/1.1 {int(code)}\r\n".encode("utf-8"))

    handler.send_response = _send_response  # type: ignore[assignment]
    handler.send_header = lambda *a, **k: None  # type: ignore[assignment]
    handler.end_headers = lambda: None  # type: ignore[assignment]
    return handler


@pytest.fixture
def config(tmp_path) -> AppConfig:
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    profiles_dir = tmp_path / "profiles"
    for d in (data_dir, outputs_dir, profiles_dir):
        d.mkdir(parents=True, exist_ok=True)
    return AppConfig(data_dir=data_dir, outputs_dir=outputs_dir, profiles_dir=profiles_dir)


# --------------------------------------------------------------------------- #
# run_server / main: non-loopback bind guard                                   #
# --------------------------------------------------------------------------- #


def test_run_server_refuses_non_loopback_without_allow_remote(monkeypatch):
    # Arrange: fail loudly if a socket is ever created.
    def _boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("JobAgentServer must not be constructed")

    monkeypatch.setattr(server_mod, "JobAgentServer", _boom)
    monkeypatch.setattr(server_mod, "configure_logging", lambda: None, raising=False)

    # Act / Assert: the guard raises SystemExit before any bind.
    with pytest.raises(SystemExit) as exc:
        server_mod.run_server(host="0.0.0.0", port=0, open_browser=False, allow_remote=False)
    assert "allow-remote" in str(exc.value)


def test_run_server_loopback_does_not_trip_guard(monkeypatch):
    """A loopback host passes the guard; we stop right after by faking the server."""
    constructed: dict = {}

    class _FakeHttpd:
        def __init__(self, addr, handler, config):
            constructed["addr"] = addr

        def serve_forever(self):
            raise KeyboardInterrupt  # simulate Ctrl+C to exit immediately

        def server_close(self):
            constructed["closed"] = True

    monkeypatch.setattr(server_mod, "JobAgentServer", _FakeHttpd)
    monkeypatch.setattr(server_mod, "configure_logging", lambda: None, raising=False)
    monkeypatch.setattr(server_mod, "configured_app", lambda: AppConfig())

    server_mod.run_server(host="127.0.0.1", port=8765, open_browser=False, allow_remote=False)

    assert constructed["addr"] == ("127.0.0.1", 8765)
    assert constructed["closed"] is True


def test_main_parses_args_and_calls_run_server(monkeypatch):
    captured: dict = {}

    def fake_run_server(*, host, port, open_browser, allow_remote):
        captured.update(host=host, port=port, open_browser=open_browser, allow_remote=allow_remote)

    monkeypatch.setattr(server_mod, "run_server", fake_run_server)
    server_mod.main(["--host", "127.0.0.1", "--port", "9999", "--no-open"])

    assert captured == {
        "host": "127.0.0.1",
        "port": 9999,
        "open_browser": False,
        "allow_remote": False,
    }


def test_main_allow_remote_flag_propagates(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(server_mod, "run_server", lambda **k: captured.update(k))
    server_mod.main(["--allow-remote", "--no-open"])
    assert captured["allow_remote"] is True


# --------------------------------------------------------------------------- #
# _send_index: token injection                                                 #
# --------------------------------------------------------------------------- #


def test_send_index_injects_csrf_meta_tag(config):
    handler = _make_handler(config)
    handler._send_index()
    body = handler.wfile.getvalue().decode("utf-8")
    assert 'name="csrf-token"' in body
    assert server_mod.SESSION_TOKEN in body


class _DivPath:
    """A STATIC_DIR stand-in whose ``index.html`` read always fails."""

    def __truediv__(self, other):
        return self

    def read_text(self, encoding="utf-8"):
        raise OSError("missing")


def test_send_index_missing_file_returns_404(config, monkeypatch):
    # Force the index read to fail so the OSError branch runs.
    monkeypatch.setattr(server_mod, "STATIC_DIR", _DivPath())
    captured: dict = {}
    handler = _make_handler(config)
    handler._send_error_json = lambda msg, status=400: captured.update(msg=msg, status=int(status))  # type: ignore[assignment]

    handler._send_index()
    assert captured["status"] == 404


# --------------------------------------------------------------------------- #
# _send_static: containment + missing-file branches                            #
# --------------------------------------------------------------------------- #


def test_send_static_serves_existing_file(config):
    handler = _make_handler(config)
    real = server_mod.STATIC_DIR / "app.js"
    handler._send_static(real)
    body = handler.wfile.getvalue()
    # The HTTP status line plus the file bytes were written.
    assert b"HTTP/1.1 200" in body
    assert len(body) > len(b"HTTP/1.1 200\r\n")


def test_send_static_rejects_path_outside_static_dir(config):
    handler = _make_handler(config)
    captured: dict = {}
    handler._send_error_json = lambda msg, status=400: captured.update(status=int(status))  # type: ignore[assignment]
    handler._send_static(server_mod.STATIC_DIR / ".." / ".." / "secret.txt")
    assert captured["status"] == 404


def test_send_static_missing_file_returns_404(config):
    handler = _make_handler(config)
    captured: dict = {}
    handler._send_error_json = lambda msg, status=400: captured.update(status=int(status))  # type: ignore[assignment]
    handler._send_static(server_mod.STATIC_DIR / "does-not-exist.js")
    assert captured["status"] == 404


# --------------------------------------------------------------------------- #
# _send_file: allowed-root containment                                         #
# --------------------------------------------------------------------------- #


def test_send_file_serves_file_inside_data_dir(config):
    target = config.outputs_dir / "report.txt"
    target.write_text("hello", encoding="utf-8")
    handler = _make_handler(config)
    handler._send_file(str(target))
    assert b"HTTP/1.1 200" in handler.wfile.getvalue()


def test_send_file_rejects_path_outside_allowed_roots(config, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    handler = _make_handler(config)
    captured: dict = {}
    handler._send_error_json = lambda msg, status=400: captured.update(status=int(status))  # type: ignore[assignment]
    handler._send_file(str(outside))
    assert captured["status"] == 404


# --------------------------------------------------------------------------- #
# JSON helpers                                                                  #
# --------------------------------------------------------------------------- #


def test_send_error_json_sets_message_and_status(config):
    handler = _make_handler(config)
    handler._send_error_json("nope", 422)
    body = handler.wfile.getvalue().decode("utf-8")
    assert "HTTP/1.1 422" in body
    assert '"error"' in body
    assert "nope" in body


def test_send_json_swallows_broken_pipe(config):
    handler = _make_handler(config)

    class _BrokenWFile:
        def write(self, *a, **k):
            raise BrokenPipeError

    handler.wfile = _BrokenWFile()  # type: ignore[assignment]
    # Should not raise — the disconnect is swallowed.
    handler._send_json({"x": 1})


# --------------------------------------------------------------------------- #
# get_portfolio GET handlers via a live loopback server                        #
# --------------------------------------------------------------------------- #


@pytest.fixture
def live_server(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, configured_app())
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get_raw(port: int, path: str) -> tuple[int, str, str]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", path)
        resp = conn.getresponse()
        ctype = resp.getheader("Content-Type") or ""
        raw = resp.read().decode("utf-8")
    return resp.status, ctype, raw


def test_portfolio_preview_inlines_css(live_server, monkeypatch):
    from job_agent.ui.routes import get_portfolio

    html = '<html><head><link rel="stylesheet" href="style.css" /></head><body>hi</body></html>'
    monkeypatch.setattr(get_portfolio, "_portfolio_read", lambda config: {"html": html, "css": "body{color:red}"})
    port = live_server

    status, ctype, body = _get_raw(port, "/api/portfolio/preview")
    assert status == 200
    assert "text/html" in ctype
    assert "<style>" in body
    assert 'href="style.css"' not in body


def test_portfolio_style_css_returns_css(live_server, monkeypatch):
    from job_agent.ui.routes import get_portfolio

    monkeypatch.setattr(get_portfolio, "_portfolio_read", lambda config: {"html": "", "css": ".x{margin:0}"})
    port = live_server

    status, ctype, body = _get_raw(port, "/api/portfolio/style.css")
    assert status == 200
    assert "text/css" in ctype
    assert body == ".x{margin:0}"


def test_portfolio_asset_missing_returns_404(live_server, monkeypatch):
    from job_agent.ui.routes import get_portfolio

    monkeypatch.setattr(get_portfolio, "_portfolio_state", lambda config: {"path": str(get_portfolio.Path.cwd())})
    port = live_server

    status, _, body = _get_raw(port, "/api/portfolio/no-such-asset.png")
    assert status == 404
    assert "error" in (json.loads(body) if body else {})


def test_get_portfolio_returns_read_payload(live_server, monkeypatch):
    from job_agent.ui.routes import get_portfolio

    monkeypatch.setattr(get_portfolio, "_portfolio_read", lambda config: {"html": "<h1>", "css": "", "exists": True})
    port = live_server

    status, _, body = _get_raw(port, "/api/portfolio")
    assert status == 200
    assert json.loads(body)["exists"] is True
