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

from job_agent.ai_agent import (
    analyze_fit as _ai_analyze_fit,
    chat_about_job as _ai_chat_about_job,
    classify_job as _ai_classify_job,
    summarize_job as _ai_summarize_job,
    suggest_search_queries,
)
from job_agent.analytics import compute_stats, jobs_to_csv
from job_agent.autopilot import AutopilotConfig, get_autopilot
from job_agent.config import AppConfig
from job_agent.coach import build_coach_plan as _coach_plan
from job_agent.cv_studio import (
    compile_preview as _studio_compile_preview,
    load_studio as _studio_load,
    promote_draft_to_main as _studio_promote_main,
    reorder_sections as _studio_reorder,
    reset_studio_draft as _studio_reset,
    save_studio_draft as _studio_save,
    suggest_edits as _studio_suggest,
)
from job_agent.cv_template import import_cv_template_upload
from job_agent.db.database import Database
from job_agent.enrichment import EnrichOptions, enrich_job
from job_agent.exporters.internship_workbook import export_applied_internships
from job_agent.ollama_manage import (
    list_all_pulls,
    ollama_install_status,
    pull_model as _pull_ollama_model,
    pull_status as _ollama_pull_status,
    start_ollama_server,
)
from job_agent.polish import PolishOptions, ollama_status, resolve_ollama_model
from job_agent.profile_enrich import enrich_from_github, enrich_from_linkedin_skills
from job_agent.intake.free_apis import (
    FreeApiError,
    KEYWORD_ONLY_SOURCES,
    search_all_free_sources,
    search_free_api_jobs,
    supported_source_names,
)
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
from job_agent.validators import load_profile_bundle


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
    """Fetch all jobs + their enrichments / AI cache / latest packet in 4 queries
    instead of N*3 — significantly faster on databases with 50+ jobs."""
    tracker = _tracker(config)
    status_filter = JobStatus(status) if status else None
    jobs = tracker.list_jobs(status=status_filter)
    if not jobs:
        return []
    job_ids = [job.id for job in jobs]
    enrichments = tracker.db.bulk_get_enrichments(job_ids)
    ai_caches = tracker.db.bulk_list_ai_cache(job_ids)
    latest_packets = tracker.db.bulk_latest_packets(job_ids)
    results: list[dict] = []
    for job in jobs:
        results.append(job_to_dict(
            job,
            latest_packets.get(job.id),
            enrichment=enrichments.get(job.id),
            ai_cache=ai_caches.get(job.id, {}),
        ))
    return results


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


def _enrich_batch(config: AppConfig, payload: dict) -> dict:
    job_ids = payload.get("job_ids") or []
    results: list[dict] = []
    options = EnrichOptions(
        rome=bool(payload.get("rome", True)),
        anotea=bool(payload.get("anotea", True)),
        training=bool(payload.get("training", True)),
        labour_market=bool(payload.get("labour_market", True)),
        territory=bool(payload.get("territory", True)),
        employer=bool(payload.get("employer", True)),
        other=bool(payload.get("other", True)),
    )
    for job_id in job_ids:
        try:
            report = enrich_job(config, str(job_id), options)
            results.append({"job_id": job_id, "ok": True, "sources": report.get("sources")})
        except Exception as exc:
            results.append({"job_id": job_id, "ok": False, "error": str(exc)})
    return {"count": len(results), "results": results}


def _multi_source_search(config: AppConfig, payload: dict) -> dict:
    query = str(payload.get("query") or "")
    location = str(payload.get("location") or "")
    limit_per_source = _safe_int(payload.get("limit_per_source"), 8, maximum=30)
    sources_raw = payload.get("sources")
    if isinstance(sources_raw, str):
        sources = [s.strip() for s in sources_raw.split(",") if s.strip()]
    elif isinstance(sources_raw, list):
        sources = [str(s).strip() for s in sources_raw if str(s).strip()]
    else:
        sources = list(KEYWORD_ONLY_SOURCES)
    save = bool(payload.get("save", True))
    prepare_packets = bool(payload.get("prepare_packets", False))
    force_packets = bool(payload.get("force_packets", False))
    internships_only = bool(payload.get("internships_only", False))
    remote_only = bool(payload.get("remote_only", False))
    min_relevance = _safe_int(payload.get("min_relevance"), 0, minimum=0, maximum=100)
    france_eu_only = bool(payload.get("france_eu_only", False))
    radius_km = _safe_int(payload.get("radius_km"), 0, minimum=0, maximum=100)
    aggregate = search_all_free_sources(
        query=query,
        location=location,
        limit_per_source=limit_per_source,
        sources=sources,
        remote_only=remote_only,
        internships_only=internships_only,
        min_relevance=min_relevance,
        france_eu_only=france_eu_only,
        radius_km=radius_km,
        use_cache=True,
        cache_ttl_hours=6.0,
    )
    if save:
        save_result = _save_jobs(config, aggregate["jobs"], prepare_packets=prepare_packets, force_packets=force_packets)
    else:
        save_result = {
            "jobs": [job_to_dict(job) for job in aggregate["jobs"]],
            "imported": 0,
            "duplicates": 0,
            "prepared": 0,
            "failures": [],
        }
    save_result.update({
        "per_source": aggregate["per_source"],
        "errors": aggregate["errors"],
        "found": len(aggregate["jobs"]),
        "sources": sources,
    })
    return save_result


def _api_search(config: AppConfig, payload: dict) -> dict:
    source = str(payload.get("source") or "francetravail")
    query = str(payload.get("query") or "data scientist")
    location = str(payload.get("location") or "Paris")
    limit = _safe_int(payload.get("limit"), 10, maximum=50)
    save = bool(payload.get("save", True))
    prepare_packets = bool(payload.get("prepare_packets", False))
    force_packets = bool(payload.get("force_packets", False))
    internships_only = bool(payload.get("internships_only", False))
    min_relevance = _safe_int(payload.get("min_relevance"), 0, minimum=0, maximum=100)
    france_eu_only = bool(payload.get("france_eu_only", False))
    radius_km = _safe_int(payload.get("radius_km"), 0, minimum=0, maximum=100)
    jobs = search_free_api_jobs(
        source,
        query=query,
        location=location,
        limit=limit,
        internships_only=internships_only,
        min_relevance=min_relevance,
        france_eu_only=france_eu_only,
        radius_km=radius_km,
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
    include_multi_source = bool(payload.get("include_multi_source", True))
    min_relevance = _safe_int(payload.get("min_relevance"), 0, minimum=0, maximum=100)
    france_eu_only = bool(payload.get("france_eu_only", False))
    radius_km = _safe_int(payload.get("radius_km"), 0, minimum=0, maximum=100)
    links = _search_links({"query": query, "location": location, "language": language, "limit": limit_queries, "boards": "recommended"})
    try:
        profile, master_cv, _ = load_profile_bundle(config)
        query_plan = suggest_search_queries(
            profile,
            master_cv,
            seed_query=query,
            location=location,
            language=language,
            internships_only=internships_only,
            limit=limit_queries,
        )
    except Exception:
        query_plan = {
            "queries": [group["query"] for group in links["groups"]],
            "rationale": "Profile loading failed; deterministic query expansion used.",
            "used_ai": False,
            "model": "",
        }
    api_queries = [str(item).strip() for item in query_plan.get("queries", []) if str(item).strip()] or [group["query"] for group in links["groups"]]
    if not is_france_travail_configured():
        return {
            "api_configured": False,
            "message": "France Travail API credentials are not configured, so I prepared curated manual links instead.",
            "manual": links,
            "query_plan": query_plan,
            "imported": 0,
            "duplicates": 0,
            "prepared": 0,
            "jobs": [],
            "failures": [],
            "multi_source": None,
        }

    imported = duplicates = prepared = 0
    jobs_out: list[dict] = []
    failures: list[str] = []
    france_found = 0
    for api_query in api_queries[:limit_queries]:
        try:
            jobs = search_free_api_jobs(
                "francetravail",
                query=api_query,
                location=location,
                limit=limit_per_query,
                internships_only=internships_only,
                min_relevance=min_relevance,
                france_eu_only=france_eu_only,
                radius_km=radius_km,
                use_cache=True,
                cache_ttl_hours=6.0,
            )
        except Exception as exc:
            failures.append(f"{api_query}: {exc}")
            continue
        france_found += len(jobs)
        saved = _save_jobs(config, jobs, prepare_packets=prepare_packets, force_packets=force_packets)
        imported += saved["imported"]
        duplicates += saved["duplicates"]
        prepared += saved["prepared"]
        failures.extend(saved["failures"])
        jobs_out.extend(saved["jobs"])

    multi_summary = None
    if include_multi_source:
        per_source: dict[str, int] = {}
        errors: dict[str, str] = {}
        multi_found = multi_imported = multi_duplicates = multi_prepared = 0
        for api_query in api_queries[: min(3, len(api_queries))]:
            try:
                aggregate = search_all_free_sources(
                    query=api_query,
                    location=location,
                    limit_per_source=max(1, min(limit_per_query, 5)),
                    sources=list(KEYWORD_ONLY_SOURCES),
                    internships_only=internships_only,
                    min_relevance=min_relevance,
                    france_eu_only=france_eu_only,
                    radius_km=radius_km,
                    use_cache=True,
                    cache_ttl_hours=6.0,
                )
            except Exception as exc:
                errors[f"multi/{api_query}"] = str(exc)
                continue
            multi_found += len(aggregate["jobs"])
            for source, count in (aggregate.get("per_source") or {}).items():
                per_source[source] = per_source.get(source, 0) + int(count or 0)
            for source, err in (aggregate.get("errors") or {}).items():
                errors[source] = str(err)
            saved = _save_jobs(config, aggregate["jobs"], prepare_packets=prepare_packets, force_packets=force_packets)
            multi_imported += saved["imported"]
            multi_duplicates += saved["duplicates"]
            multi_prepared += saved["prepared"]
            imported += saved["imported"]
            duplicates += saved["duplicates"]
            prepared += saved["prepared"]
            failures.extend(saved["failures"])
            jobs_out.extend(saved["jobs"])
        multi_summary = {
            "found": multi_found,
            "imported": multi_imported,
            "duplicates": multi_duplicates,
            "prepared": multi_prepared,
            "per_source": per_source,
            "errors": errors,
        }
    return {
        "api_configured": True,
        "message": "Smart 1-click hunt finished.",
        "manual": links,
        "query_plan": query_plan,
        "imported": imported,
        "duplicates": duplicates,
        "prepared": prepared,
        "found": france_found + (multi_summary or {}).get("found", 0),
        "jobs": jobs_out,
        "failures": failures,
        "multi_source": multi_summary,
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
        if parsed.path == "/api/autopilot":
            return self._send_json(get_autopilot(self._config()).status())
        if parsed.path == "/api/autopilot/stream":
            return self._stream_autopilot()
        if parsed.path == "/api/cv-studio":
            return self._send_json(_studio_load(self._config()))
        if parsed.path == "/api/cv-studio/preview-pdf":
            studio = Path(self._config().data_dir or Path.cwd() / ".job_agent") / "cv_studio" / "preview.pdf"
            if not studio.exists():
                return self._send_error_json("Preview not built yet.", HTTPStatus.NOT_FOUND)
            try:
                body = studio.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
            return None
        if parsed.path == "/api/ai-status":
            return self._send_json(ollama_status(PolishOptions.from_env()))
        if parsed.path == "/api/ollama-install":
            return self._send_json(ollama_install_status(PolishOptions.from_env()))
        if parsed.path == "/api/ollama-pull-status":
            query = parse_qs(parsed.query)
            model = (query.get("model") or [""])[0]
            return self._send_json({"status": _ollama_pull_status(model) if model else _ollama_pull_status(), "pulls": list_all_pulls()})
        if parsed.path == "/api/ai-cache":
            query = parse_qs(parsed.query)
            job_id = (query.get("job_id") or [""])[0]
            if not job_id:
                return self._send_error_json("job_id is required.")
            config = self._config()
            db = Database(config.db_path)  # type: ignore[arg-type]
            db.initialize()
            return self._send_json({"cache": db.list_ai_cache_for_job(job_id)})
        if parsed.path == "/api/stats":
            config = self._config()
            db = Database(config.db_path)  # type: ignore[arg-type]
            db.initialize()
            return self._send_json(compute_stats(db))
        if parsed.path == "/api/export-csv":
            config = self._config()
            db = Database(config.db_path)  # type: ignore[arg-type]
            db.initialize()
            csv_text = jobs_to_csv(db.list_jobs(limit=None))
            body = csv_text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="job-agent-jobs.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return None
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
            if parsed.path == "/api/multi-search":
                return self._send_json(_multi_source_search(config, payload))
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
            if parsed.path == "/api/enrich":
                job_id = str(payload.get("job_id") or "")
                if not job_id:
                    return self._send_error_json("job_id is required.")
                options = EnrichOptions(
                    rome=bool(payload.get("rome", True)),
                    anotea=bool(payload.get("anotea", True)),
                    training=bool(payload.get("training", True)),
                    labour_market=bool(payload.get("labour_market", True)),
                    territory=bool(payload.get("territory", True)),
                    employer=bool(payload.get("employer", True)),
                    other=bool(payload.get("other", True)),
                )
                report = enrich_job(config, job_id, options)
                return self._send_json({"report": report})
            if parsed.path == "/api/enrich-batch":
                return self._send_json(_enrich_batch(config, payload))
            if parsed.path == "/api/autopilot/start":
                autopilot_options = AutopilotConfig(
                    queries=[q.strip() for q in (payload.get("queries") or []) if str(q).strip()] or AutopilotConfig().queries,
                    location=str(payload.get("location") or "Paris"),
                    language=str(payload.get("language") or "both"),
                    interval_minutes=int(payload.get("interval_minutes") or 30),
                    auto_packet_threshold=int(payload.get("auto_packet_threshold") or 75),
                    multi_source_limit=int(payload.get("multi_source_limit") or 5),
                    france_travail_limit=int(payload.get("france_travail_limit") or 8),
                    radius_km=_safe_int(payload.get("radius_km"), 25, minimum=0, maximum=100),
                    min_relevance=_safe_int(payload.get("min_relevance"), 50, minimum=0, maximum=100),
                    france_eu_only=bool(payload.get("france_eu_only", True)),
                    use_france_travail=bool(payload.get("use_france_travail", True)),
                    use_multi_source=bool(payload.get("use_multi_source", True)),
                    max_packets_per_cycle=int(payload.get("max_packets_per_cycle") or 5),
                    internships_only=bool(payload.get("internships_only", True)),
                    email_notify=bool(payload.get("email_notify", False)),
                )
                state = get_autopilot(config).start(autopilot_options)
                return self._send_json({"state": state.__dict__, "status": get_autopilot(config).status()})
            if parsed.path == "/api/autopilot/stop":
                state = get_autopilot(config).stop()
                return self._send_json({"state": state.__dict__, "status": get_autopilot(config).status()})
            if parsed.path == "/api/coach-plan":
                return self._send_json(_coach_plan(config))
            if parsed.path == "/api/cv-studio/save":
                text = str(payload.get("text") or "")
                return self._send_json(_studio_save(config, text))
            if parsed.path == "/api/cv-studio/reset":
                return self._send_json(_studio_reset(config))
            if parsed.path == "/api/cv-studio/promote":
                return self._send_json(_studio_promote_main(config))
            if parsed.path == "/api/cv-studio/compile":
                text = payload.get("text")
                return self._send_json(_studio_compile_preview(config, text if isinstance(text, str) else None))
            if parsed.path == "/api/cv-studio/reorder":
                text = str(payload.get("text") or "")
                order_raw = payload.get("order") or []
                order = [str(item) for item in order_raw if str(item).strip()]
                rewritten = _studio_reorder(text, order)
                return self._send_json({"ok": True, "text": rewritten})
            if parsed.path == "/api/cv-studio/suggest":
                text = str(payload.get("text") or "")
                job_context = str(payload.get("job_context") or "")
                return self._send_json(_studio_suggest(text, job_context))
            if parsed.path == "/api/ai-chat":
                job_id = str(payload.get("job_id") or "")
                question = str(payload.get("question") or "").strip()
                history = payload.get("history") or []
                if not job_id or not question:
                    return self._send_error_json("job_id and question are required.")
                db = Database(config.db_path)  # type: ignore[arg-type]
                db.initialize()
                job = db.resolve_job(job_id)
                if not job:
                    return self._send_error_json("Job not found.", HTTPStatus.NOT_FOUND)
                profile, master_cv, _ = load_profile_bundle(config)
                reply = _ai_chat_about_job(job, master_cv, profile, question, history if isinstance(history, list) else [])
                if not reply:
                    return self._send_error_json(
                        "AI chat unavailable. Start Ollama (and make sure a model is pulled) to enable this.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                return self._send_json({"reply": reply})
            if parsed.path == "/api/ai-summarize":
                job_id = str(payload.get("job_id") or "")
                if not job_id:
                    return self._send_error_json("job_id is required.")
                db = Database(config.db_path)  # type: ignore[arg-type]
                db.initialize()
                job = db.resolve_job(job_id)
                if not job:
                    return self._send_error_json("Job not found.", HTTPStatus.NOT_FOUND)
                tldr = _ai_summarize_job(job)
                if not tldr:
                    return self._send_error_json("AI summary unavailable.", HTTPStatus.SERVICE_UNAVAILABLE)
                try:
                    db.save_ai_cache(job.id, "summary", tldr, resolve_ollama_model())
                except Exception:
                    pass
                return self._send_json({"summary": tldr})
            if parsed.path == "/api/ai-classify":
                job_id = str(payload.get("job_id") or "")
                if not job_id:
                    return self._send_error_json("job_id is required.")
                db = Database(config.db_path)  # type: ignore[arg-type]
                db.initialize()
                job = db.resolve_job(job_id)
                if not job:
                    return self._send_error_json("Job not found.", HTTPStatus.NOT_FOUND)
                classification = _ai_classify_job(job)
                if not classification:
                    return self._send_error_json("AI classify unavailable.", HTTPStatus.SERVICE_UNAVAILABLE)
                try:
                    db.save_ai_cache(job.id, "classify", classification, resolve_ollama_model())
                except Exception:
                    pass
                return self._send_json({"classification": classification})
            if parsed.path == "/api/ollama-launch":
                result = start_ollama_server(PolishOptions.from_env())
                return self._send_json(result)
            if parsed.path == "/api/ollama-pull":
                model = str(payload.get("model") or "").strip() or "llama3.2:3b"
                return self._send_json(_pull_ollama_model(model, PolishOptions.from_env()))
            if parsed.path == "/api/ai-plan-queries":
                profile, master_cv, _ = load_profile_bundle(config)
                plan = suggest_search_queries(
                    profile,
                    master_cv,
                    seed_query=str(payload.get("seed_query") or "data scientist"),
                    location=str(payload.get("location") or "Paris"),
                    language=str(payload.get("language") or "both"),
                    internships_only=bool(payload.get("internships_only", True)),
                    limit=int(payload.get("limit") or 8),
                )
                return self._send_json(plan)
            if parsed.path == "/api/ai-analyze":
                job_id = str(payload.get("job_id") or "")
                if not job_id:
                    return self._send_error_json("job_id is required.")
                db = Database(config.db_path)  # type: ignore[arg-type]
                db.initialize()
                job = db.resolve_job(job_id)
                if not job:
                    return self._send_error_json("Job not found.", HTTPStatus.NOT_FOUND)
                profile, master_cv, _ = load_profile_bundle(config)
                analysis = _ai_analyze_fit(job, master_cv, profile, PolishOptions.from_env())
                if analysis is None:
                    return self._send_error_json(
                        "AI analysis unavailable. Start Ollama and make sure at least one local model is installed.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                return self._send_json({"analysis": analysis.to_dict()})
            if parsed.path == "/api/enrich-github":
                handle = str(payload.get("handle") or "").strip()
                if not handle and config.profiles_dir:
                    try:
                        import json as _j
                        profile_json = _j.loads((config.profiles_dir / "candidate_profile.json").read_text(encoding="utf-8"))
                        github_url = (profile_json.get("contact") or {}).get("github_url") or ""
                        handle = github_url.rstrip("/").rsplit("/", 1)[-1] if github_url else ""
                    except Exception:
                        handle = ""
                if not handle:
                    return self._send_error_json("GitHub handle is required. Set contact.github_url in candidate_profile.json or pass 'handle'.")
                report = enrich_from_github(Path(config.profiles_dir), handle, add_projects=bool(payload.get("add_projects", True)))
                return self._send_json({"report": report})
            if parsed.path == "/api/enrich-linkedin":
                text = str(payload.get("text") or "")
                report = enrich_from_linkedin_skills(Path(config.profiles_dir), text)
                return self._send_json({"report": report})
            if parsed.path == "/api/export-internships":
                return self._send_json(_export_internships(config, payload))
            if parsed.path == "/api/import-cv-template":
                filename = str(payload.get("filename") or "").strip()
                content = str(payload.get("content_base64") or "").strip()
                if not filename or not content:
                    return self._send_error_json("filename and content_base64 are required.")
                return self._send_json(import_cv_template_upload(config, filename=filename, content_base64=content))
            if parsed.path == "/api/status":
                job_id = str(payload.get("job_id") or "")
                status = JobStatus(str(payload.get("status") or ""))
                tracker = _tracker(config)
                tracker.update_status(job_id, status, note=str(payload.get("note") or ""))
                return self._send_json({"ok": True})
            if parsed.path == "/api/delete-job":
                job_id = str(payload.get("job_id") or "")
                if not job_id:
                    return self._send_error_json("job_id is required.")
                tracker = _tracker(config)
                deleted_id = tracker.delete_job(job_id, note=str(payload.get("note") or "Dashboard removal"))
                return self._send_json({"ok": True, "deleted_id": deleted_id})
            return self._send_error_json("Unknown API route.", HTTPStatus.NOT_FOUND)
        except FreeApiError as exc:
            return self._send_error_json(str(exc), HTTPStatus.BAD_GATEWAY)
        except Exception as exc:
            return self._send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

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
            return None
        return None

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
