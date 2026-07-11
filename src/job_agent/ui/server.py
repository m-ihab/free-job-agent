"""No-dependency local web dashboard for free-job-agent."""
from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

from job_agent.ui.security import SESSION_TOKEN, check_request, is_loopback_host

from job_agent import auto_apply as _auto_apply
from job_agent.autopilot import get_autopilot
from job_agent.config import AppConfig
from job_agent.intake.free_apis import FreeApiError
from job_agent.ui import routes as _routes
from job_agent.ui.routes import GET_ROUTES, POST_ROUTES
# Re-exported for backward compatibility; the implementations now live in
# ``job_agent.ui.route_helpers`` so the route modules can import them without a
# circular dependency on this module.
from job_agent.ui.route_helpers import (  # noqa: F401
    STATIC_DIR,
    _api_search,
    _enrich_batch,
    _export_internships,
    _file_response_path,
    _json_bytes,
    _latest_packet_for_job,
    _list_jobs,
    _multi_source_search,
    _needs_manual_jobs,
    _one_click_hunt,
    _read_json,
    _resolve_github_handle,
    _safe_int,
    _save_jobs,
    _search_links,
    _tracker,
)
from job_agent.ui.services import (
    APP_NAME,
    configured_app,
)

logger = logging.getLogger(__name__)


class JobAgentHandler(BaseHTTPRequestHandler):
    server_version = "JobAgentUI/0.1"

    def _config(self) -> AppConfig:
        return self.server.config  # type: ignore[attr-defined]

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        # Client disconnects (browser tab closed, page reloaded mid-response,
        # SSE timeouts) raise ConnectionAbortedError / BrokenPipeError when we
        # try to write back. Those aren't application errors — the request is
        # simply gone — so we swallow them silently here.
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            return None

    def _send_json(self, payload: object, status: int = HTTPStatus.OK) -> None:
        self._send(int(status), _json_bytes(payload))

    def _send_error_json(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self._send_json({"error": message}, status)

    def handle_one_request(self) -> None:  # noqa: D401
        """Suppress client-disconnect tracebacks from the http.server base."""
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def log_error(self, format: str, *args) -> None:  # noqa: A002, D401
        message = format % args if args else format
        # The base class logs to stderr; downgrade noisy client-disconnects.
        if "10053" in message or "10054" in message or "Broken pipe" in message:
            return
        sys.stderr.write("[job-agent-ui] " + message + "\n")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        # Validate the Host header for GET too: ~a dozen GET routes return real
        # data (/api/jobs, /api/export-csv, /file, CV/portfolio assets) and a
        # DNS-rebinding page could otherwise read them. check_request short-
        # circuits after the Host check for non-mutating methods, so this only
        # enforces the host allowlist (no token needed for reads).
        server_address = cast("tuple[object, ...]", self.server.server_address)
        bound_host, bound_port = server_address[0], int(server_address[1])  # type: ignore[call-overload]
        ok, reason = check_request(self, "GET", bound_host=str(bound_host), bound_port=bound_port)
        if not ok:
            logger.warning("Blocked GET %s (%s)", parsed.path, reason)
            return self._send_error_json("Forbidden.", HTTPStatus.FORBIDDEN)
        if parsed.path == "/":
            return self._send_index()
        if parsed.path.startswith("/static/"):
            return self._send_static(STATIC_DIR / parsed.path.removeprefix("/static/"))
        handler = GET_ROUTES.get(parsed.path)
        if handler is not None:
            return handler(self)
        # The ``/api/portfolio/`` prefix is matched after the exact portfolio
        # routes (which live in GET_ROUTES) — preserving the original ordering,
        # including ``/api/portfolio/export`` falling through to this asset
        # lookup just as it did before.
        if parsed.path.startswith("/api/portfolio/"):
            return _routes.get_portfolio_asset(self, parsed)
        if parsed.path == "/file":
            query = parse_qs(parsed.query)
            raw_path = (query.get("path") or [""])[0]
            return self._send_file(raw_path)
        return self._send_static(STATIC_DIR / parsed.path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        # TCP servers expose server_address as a (host, port) tuple.
        server_address = cast("tuple[object, ...]", self.server.server_address)
        bound_host, bound_port = server_address[0], int(server_address[1])  # type: ignore[call-overload]
        ok, reason = check_request(self, "POST", bound_host=str(bound_host), bound_port=bound_port)
        if not ok:
            logger.warning("Blocked POST %s (%s)", parsed.path, reason)
            return self._send_error_json("Forbidden.", HTTPStatus.FORBIDDEN)
        body_len = int(self.headers.get("Content-Length", "0") or 0)
        if body_len > 0:
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if ctype and ctype != "application/json":
                return self._send_error_json(
                    "Content-Type must be application/json.", HTTPStatus.UNSUPPORTED_MEDIA_TYPE
                )
        try:
            payload = _read_json(self)
            handler = POST_ROUTES.get(parsed.path)
            if handler is not None:
                return handler(self, payload)
            return self._send_error_json("Unknown API route.", HTTPStatus.NOT_FOUND)
        except json.JSONDecodeError:
            return self._send_error_json("Malformed JSON body.", HTTPStatus.BAD_REQUEST)
        except FreeApiError as exc:
            return self._send_error_json(str(exc), HTTPStatus.BAD_GATEWAY)
        except Exception:
            logger.exception("Unhandled error in POST %s", parsed.path)
            return self._send_error_json("Internal server error.", HTTPStatus.INTERNAL_SERVER_ERROR)

    def _stream_autopilot(self) -> None:
        """SSE stream that pushes the autopilot status every few seconds."""
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
        except Exception:
            return None
        autopilot = get_autopilot(self._config())
        last_payload = ""
        import time as _time
        try:
            for _ in range(120):  # cap at ~10 minutes per stream connection
                status = autopilot.status()
                payload = json.dumps(status, ensure_ascii=False)
                if payload != last_payload:
                    chunk = f"event: status\ndata: {payload}\n\n".encode("utf-8")
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    last_payload = payload
                else:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                _time.sleep(5)
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception:
            logger.exception("autopilot SSE stream error")
            return None
        return None

    def _stream_auto_apply(self) -> None:
        """SSE stream that pushes ApplyEvent items from the auto-apply queue."""
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
        except Exception:
            return None
        q = _auto_apply.get_event_queue()
        try:
            while True:
                try:
                    event = q.get(timeout=5)
                    payload = json.dumps({
                        "kind": event.kind,
                        "job_id": event.job_id,
                        "packet_id": event.packet_id,
                        "message": event.message,
                        "summary": event.summary,
                        "screenshot_b64": event.screenshot_b64,
                        "data": event.data,
                    }, ensure_ascii=False)
                    chunk = f"event: apply\ndata: {payload}\n\n".encode("utf-8")
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    if event.kind in ("done", "error"):
                        break
                except Exception:
                    # Timeout — send keepalive ping
                    try:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
        except (BrokenPipeError, ConnectionResetError):
            pass
        return None

    def _send_index(self) -> None:
        """Serve index.html with the per-process CSRF token injected as a meta tag.

        A cross-origin page cannot read this token (same-origin HTML), and every
        mutating fetch echoes it back via the ``X-Job-Agent-Token`` header.
        """
        index = STATIC_DIR / "index.html"
        try:
            html_text = index.read_text(encoding="utf-8")
        except OSError:
            return self._send_error_json("Not found.", HTTPStatus.NOT_FOUND)
        meta = f'<meta name="csrf-token" content="{SESSION_TOKEN}">'
        if "<head>" in html_text:
            html_text = html_text.replace("<head>", f"<head>\n    {meta}", 1)
        else:
            html_text = meta + html_text
        self._send(HTTPStatus.OK, html_text.encode("utf-8"), "text/html; charset=utf-8")

    def _send_static(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            resolved.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return self._send_error_json("Not found.", HTTPStatus.NOT_FOUND)
        if not resolved.exists() or not resolved.is_file():
            return self._send_error_json("Not found.", HTTPStatus.NOT_FOUND)
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, resolved.read_bytes(), content_type)

    def _send_file(self, raw_path: str) -> None:
        path = _file_response_path(self._config(), raw_path)
        if not path:
            return self._send_error_json("File is not available from the local app.", HTTPStatus.NOT_FOUND)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, path.read_bytes(), content_type)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        sys.stderr.write("[job-agent-ui] " + format % args + "\n")


class JobAgentServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, config: AppConfig):
        super().__init__(server_address, handler_class)
        self.config = config


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    allow_remote: bool = False,
) -> None:
    from job_agent.logging_config import configure_logging
    configure_logging()
    if not is_loopback_host(host) and not allow_remote:
        raise SystemExit(
            f"Refusing to bind non-loopback host {host!r} without --allow-remote "
            "(or JOB_AGENT_UI_ALLOW_REMOTE=1). The dashboard can drive auto-apply and "
            "fetch URLs, so exposing it to the network is opt-in."
        )
    if not is_loopback_host(host):
        logger.warning(
            "WARNING: binding a non-loopback host exposes this dashboard "
            "(auto-apply, URL fetch, job data) to your network."
        )
    config = configured_app()
    try:
        server = JobAgentServer((host, port), JobAgentHandler, config)
    except OSError as exc:
        logger.error(
            "Cannot bind %s:%s (%s). Another dashboard instance is probably still "
            "running on this port — stop it or relaunch with --port <other>. "
            "A stale instance can serve a DIFFERENT database and make tracked "
            "jobs look deleted (2026-07-11 incident).",
            host,
            port,
            exc,
        )
        raise SystemExit(2) from exc
    url = f"http://{host}:{port}"
    logger.info("Starting %s at %s", APP_NAME, url)
    logger.info("Data: %s", config.data_dir)
    logger.info("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping job-agent UI.")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"Run the {APP_NAME} local web dashboard.")
    parser.add_argument("--host", default=os.environ.get("JOB_AGENT_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("JOB_AGENT_UI_PORT", "8765")))
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        default=os.environ.get("JOB_AGENT_UI_ALLOW_REMOTE") == "1",
        help="Allow binding a non-loopback host. Exposes the dashboard to the network.",
    )
    args = parser.parse_args(argv)
    run_server(
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
        allow_remote=args.allow_remote,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
