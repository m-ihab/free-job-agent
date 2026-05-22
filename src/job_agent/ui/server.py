"""No-dependency local web dashboard for free-job-agent."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.intake.free_apis import FreeApiError, search_free_api_jobs, supported_source_names
from job_agent.exporters.internship_workbook import export_applied_internships
from job_agent.pipeline import add_job_to_tracker, add_text_job, add_url_job, generate_packet_for_job
from job_agent.schemas.job import JobStatus
from job_agent.timeutil import utc_now
from job_agent.tracker import ApplicationTracker
from job_agent.ui.services import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_URL_PLACEHOLDER,
    build_manual_search_groups,
    configured_app,
    is_france_travail_configured,
    job_to_dict,
    packet_to_dict,
    profile_status,
    status_options,
)


STATIC_DIR = Path(__file__).with_name("static")


def _tracker(config: AppConfig) -> ApplicationTracker:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    return ApplicationTracker(db)


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def _safe_int(value: object, default: int, minimum: int = 1, maximum: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _file_response_path(config: AppConfig, raw_path: str) -> Path | None:
    try:
        candidate = Path(raw_path).expanduser().resolve()
    except Exception:
        return None
    roots = [config.data_dir, config.outputs_dir, config.profiles_dir]
    for root in roots:
        if root is None:
            continue
        try:
            candidate.relative_to(Path(root).resolve())
            return candidate if candidate.exists() and candidate.is_file() else None
        except ValueError:
            continue
    return None


def _latest_packet_for_job(db: Database, job_id: str):
    packets = db.get_packets_for_job(job_id)
    return packets[0] if packets else None


def _list_jobs(config: AppConfig, status: str = "") -> list[dict]:
    tracker = _tracker(config)
    status_filter = JobStatus(status) if status else None
    jobs = tracker.list_jobs(status=status_filter)
    return [job_to_dict(job, _latest_packet_for_job(tracker.db, job.id)) for job in jobs]


def _search_links(payload: dict) -> dict:
    query = str(payload.get("query") or "data scientist")
    location = str(payload.get("location") or "Paris")
    language = str(payload.get("language") or "both")
    boards = str(payload.get("boards") or "recommended")
    limit = _safe_int(payload.get("limit"), 8, maximum=30)
    groups = build_manual_search_groups(query, location, language, limit, boards)
    link_count = sum(len(group["links"]) for group in groups)
    return {"groups": groups, "query_count": len(groups), "link_count": link_count, "generated_at": utc_now()}


def _save_jobs(config: AppConfig, jobs, *, prepare_packets: bool, force_packets: bool) -> dict:
    saved: list[dict] = []
    imported = duplicates = prepared = 0
    failures: list[str] = []
    tracker = _tracker(config)
    for job in jobs:
        tracked, created = add_job_to_tracker(config, job)
        if created:
            imported += 1
        else:
            duplicates += 1
        packet = None
        if prepare_packets and created:
            try:
                packet = generate_packet_for_job(config, tracked.id, force=force_packets)
                prepared += 1
            except Exception as exc:
                failures.append(f"{tracked.title} @ {tracked.company}: {exc}")
        else:
            packet = _latest_packet_for_job(tracker.db, tracked.id)
        saved.append(job_to_dict(tracked, packet))
    return {"jobs": saved, "imported": imported, "duplicates": duplicates, "prepared": prepared, "failures": failures}


def _api_search(config: AppConfig, payload: dict) -> dict:
    source = str(payload.get("source") or "francetravail")
    query = str(payload.get("query") or "data scientist")
    location = str(payload.get("location") or "Paris")
    limit = _safe_int(payload.get("limit"), 10, maximum=50)
    save = bool(payload.get("save", True))
    prepare_packets = bool(payload.get("prepare_packets", False))
    force_packets = bool(payload.get("force_packets", False))
    internships_only = bool(payload.get("internships_only", False))
    jobs = search_free_api_jobs(
        source,
        query=query,
        location=location,
        limit=limit,
        internships_only=internships_only,
        use_cache=True,
        cache_ttl_hours=6.0,
    )
    if save:
        result = _save_jobs(config, jobs, prepare_packets=prepare_packets, force_packets=force_packets)
    else:
        result = {"jobs": [job_to_dict(job) for job in jobs], "imported": 0, "duplicates": 0, "prepared": 0, "failures": []}
    result.update({"source": source, "query": query, "location": location, "found": len(jobs)})
    return result


def _one_click_hunt(config: AppConfig, payload: dict) -> dict:
    query = str(payload.get("query") or "data scientist")
    location = str(payload.get("location") or "Paris")
    language = str(payload.get("language") or "both")
    limit_queries = _safe_int(payload.get("limit_queries"), 8, maximum=30)
    limit_per_query = _safe_int(payload.get("limit_per_query"), 5, maximum=30)
    prepare_packets = bool(payload.get("prepare_packets", False))
    force_packets = bool(payload.get("force_packets", False))
    internships_only = bool(payload.get("internships_only", False))
    links = _search_links({"query": query, "location": location, "language": language, "limit": limit_queries, "boards": "recommended"})
    if not is_france_travail_configured():
        return {
            "api_configured": False,
            "message": "France Travail API credentials are not configured, so I prepared curated manual links instead.",
            "manual": links,
            "imported": 0,
            "duplicates": 0,
            "prepared": 0,
            "jobs": [],
            "failures": [],
        }

    imported = duplicates = prepared = 0
    jobs_out: list[dict] = []
    failures: list[str] = []
    for group in links["groups"]:
        try:
            jobs = search_free_api_jobs(
                "francetravail",
                query=group["query"],
                location=location,
                limit=limit_per_query,
                internships_only=internships_only,
                use_cache=True,
                cache_ttl_hours=6.0,
            )
        except Exception as exc:
            failures.append(f"{group['query']}: {exc}")
            continue
        saved = _save_jobs(config, jobs, prepare_packets=prepare_packets, force_packets=force_packets)
        imported += saved["imported"]
        duplicates += saved["duplicates"]
        prepared += saved["prepared"]
        failures.extend(saved["failures"])
        jobs_out.extend(saved["jobs"])
    return {
        "api_configured": True,
        "message": "France Travail search finished.",
        "manual": links,
        "imported": imported,
        "duplicates": duplicates,
        "prepared": prepared,
        "jobs": jobs_out,
        "failures": failures,
    }


def _export_internships(config: AppConfig, payload: dict) -> dict:
    workbook = payload.get("workbook")
    sheet = str(payload.get("sheet") or "") or None
    workbook_path, count = export_applied_internships(config, workbook_path=workbook, sheet_name=sheet)
    return {"workbook": str(workbook_path), "count": count}


class JobAgentHandler(BaseHTTPRequestHandler):
    server_version = "JobAgentUI/0.1"

    def _config(self) -> AppConfig:
        return self.server.config  # type: ignore[attr-defined]

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: object, status: int = HTTPStatus.OK) -> None:
        self._send(int(status), _json_bytes(payload))

    def _send_error_json(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self._send_json({"error": message}, status)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._send_static(STATIC_DIR / "index.html")
        if parsed.path.startswith("/static/"):
            return self._send_static(STATIC_DIR / parsed.path.removeprefix("/static/"))
        if parsed.path == "/api/state":
            config = self._config()
            return self._send_json(
                {
                    "profile": profile_status(config),
                    "sources": supported_source_names(),
                    "statuses": status_options(),
                    "app": {
                        "name": APP_NAME,
                        "description": APP_DESCRIPTION,
                        "url": APP_URL_PLACEHOLDER,
                    },
                }
            )
        if parsed.path == "/api/jobs":
            query = parse_qs(parsed.query)
            status = (query.get("status") or [""])[0]
            try:
                return self._send_json({"jobs": _list_jobs(self._config(), status=status)})
            except ValueError as exc:
                return self._send_error_json(str(exc))
        if parsed.path == "/api/packets":
            query = parse_qs(parsed.query)
            job_id = (query.get("job_id") or [""])[0]
            db = Database(self._config().db_path)  # type: ignore[arg-type]
            db.initialize()
            packets = db.get_packets_for_job(job_id) if job_id else db.list_packets()
            return self._send_json({"packets": [packet_to_dict(packet) for packet in packets]})
        if parsed.path == "/file":
            query = parse_qs(parsed.query)
            raw_path = (query.get("path") or [""])[0]
            return self._send_file(raw_path)
        return self._send_static(STATIC_DIR / parsed.path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = _read_json(self)
            config = self._config()
            if parsed.path == "/api/search-links":
                return self._send_json(_search_links(payload))
            if parsed.path == "/api/api-search":
                return self._send_json(_api_search(config, payload))
            if parsed.path == "/api/one-click-hunt":
                return self._send_json(_one_click_hunt(config, payload))
            if parsed.path == "/api/add-url":
                url = str(payload.get("url") or "").strip()
                if not url:
                    return self._send_error_json("URL is required.")
                job, created = add_url_job(config, url)
                db = Database(config.db_path)  # type: ignore[arg-type]
                db.initialize()
                packet = _latest_packet_for_job(db, job.id)
                return self._send_json({"created": created, "job": job_to_dict(job, packet)})
            if parsed.path == "/api/add-text":
                text = str(payload.get("text") or "").strip()
                if not text:
                    return self._send_error_json("Job text is required.")
                job, created = add_text_job(
                    config,
                    text,
                    title=str(payload.get("title") or "") or None,
                    company=str(payload.get("company") or "") or None,
                    url=str(payload.get("url") or "") or None,
                )
                return self._send_json({"created": created, "job": job_to_dict(job)})
            if parsed.path == "/api/generate-packet":
                job_id = str(payload.get("job_id") or "")
                if not job_id:
                    return self._send_error_json("job_id is required.")
                packet = generate_packet_for_job(config, job_id, force=bool(payload.get("force", False)))
                return self._send_json({"packet": packet_to_dict(packet)})
            if parsed.path == "/api/export-internships":
                return self._send_json(_export_internships(config, payload))
            if parsed.path == "/api/status":
                job_id = str(payload.get("job_id") or "")
                status = JobStatus(str(payload.get("status") or ""))
                tracker = _tracker(config)
                tracker.update_status(job_id, status, note=str(payload.get("note") or ""))
                return self._send_json({"ok": True})
            return self._send_error_json("Unknown API route.", HTTPStatus.NOT_FOUND)
        except FreeApiError as exc:
            return self._send_error_json(str(exc), HTTPStatus.BAD_GATEWAY)
        except Exception as exc:
            return self._send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

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


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    config = configured_app()
    server = JobAgentServer((host, port), JobAgentHandler, config)
    url = f"http://{host}:{port}"
    print(f"Starting {APP_NAME} at {url}")
    print(f"Data: {config.data_dir}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping job-agent UI.")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"Run the {APP_NAME} local web dashboard.")
    parser.add_argument("--host", default=os.environ.get("JOB_AGENT_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("JOB_AGENT_UI_PORT", "8765")))
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
    args = parser.parse_args(argv)
    run_server(host=args.host, port=args.port, open_browser=not args.no_open)


if __name__ == "__main__":  # pragma: no cover
    main()
