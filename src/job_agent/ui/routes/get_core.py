"""GET handlers for core state, jobs, packets, stats and AI status routes."""
from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from job_agent.analytics import compute_stats
from job_agent.cv_studio import (
    ICON_PACKS as _STUDIO_ICON_PACKS,
    list_assets as _studio_list_assets,
    load_studio as _studio_load,
    read_asset as _studio_read_asset,
)
from job_agent.db.database import Database
from job_agent.intake.free_apis import supported_source_names
from job_agent.ollama_manage import (
    list_all_pulls,
    ollama_install_status,
    pull_status as _ollama_pull_status,
)
from job_agent.polish import PolishOptions, ollama_status
from job_agent import auto_apply as _auto_apply
from job_agent.autopilot import get_autopilot
from job_agent.ui.route_helpers import (
    _list_jobs,
    _needs_manual_jobs,
    _safe_int,
)
from job_agent.ui.services import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_URL_PLACEHOLDER,
    packet_to_dict,
    profile_status,
    status_options,
)


def get_state(h) -> None:
    config = h._config()
    h._send_json(
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


def get_jobs(h) -> None:
    parsed = urlparse(h.path)
    query = parse_qs(parsed.query)
    status = (query.get("status") or [""])[0]
    try:
        h._send_json({"jobs": _list_jobs(h._config(), status=status)})
    except ValueError as exc:
        h._send_error_json(str(exc))


def get_needs_manual(h) -> None:
    # Jobs full-auto handed off at a CAPTCHA/login/anti-bot wall; their
    # prepared packets are ready for the user to finish by hand.
    h._send_json({"jobs": _needs_manual_jobs(h._config())})


def get_packets(h) -> None:
    parsed = urlparse(h.path)
    query = parse_qs(parsed.query)
    job_id = (query.get("job_id") or [""])[0]
    db = Database(h._config().db_path)  # type: ignore[arg-type]
    db.initialize()
    packets = db.get_packets_for_job(job_id) if job_id else db.list_packets()
    h._send_json({"packets": [packet_to_dict(packet) for packet in packets]})


def get_autopilot_status(h) -> None:
    h._send_json(get_autopilot(h._config()).status())


def get_auto_apply_status(h) -> None:
    h._send_json(_auto_apply.get_state())


def get_auto_apply_preview(h) -> None:
    parsed = urlparse(h.path)
    query = parse_qs(parsed.query)
    raw_min = (query.get("min_score") or ["65"])[0]
    try:
        min_score = max(0.0, min(float(raw_min), 100.0))
    except (TypeError, ValueError):
        min_score = 65.0
    limit = _safe_int((query.get("limit") or ["20"])[0], 20, minimum=1, maximum=50)
    h._send_json({"candidates": _auto_apply.get_candidates_preview(min_score=min_score, limit=limit)})


def get_cv_studio(h) -> None:
    h._send_json(_studio_load(h._config()))


def get_cv_studio_assets(h) -> None:
    h._send_json({
        "assets": _studio_list_assets(h._config()),
        "icon_packs": [{"key": k, "label": v["label"]} for k, v in _STUDIO_ICON_PACKS.items()],
    })


def get_cv_studio_asset(h) -> None:
    parsed = urlparse(h.path)
    query = parse_qs(parsed.query)
    name = (query.get("name") or [""])[0]
    if not name:
        return h._send_error_json("name is required.")
    try:
        h._send_json(_studio_read_asset(h._config(), name))
    except ValueError as exc:
        h._send_error_json(str(exc))


def get_cv_studio_preview_pdf(h) -> None:
    studio = Path(h._config().data_dir or Path.cwd() / ".job_agent") / "cv_studio" / "preview.pdf"
    if not studio.exists():
        return h._send_error_json("Preview not built yet.", HTTPStatus.NOT_FOUND)
    try:
        body = studio.read_bytes()
        h.send_response(HTTPStatus.OK)
        h.send_header("Content-Type", "application/pdf")
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        h.wfile.write(body)
    except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
        pass
    return None


def get_ai_status(h) -> None:
    h._send_json(ollama_status(PolishOptions.from_env()))


def get_ai_trace(h) -> None:
    """Recent local-AI routing telemetry (per-tier latency / success rate) for
    the AI trace panel. Prompt-free by construction."""
    from job_agent.agent_core import trace_summary
    h._send_json(trace_summary())


def get_ollama_install(h) -> None:
    h._send_json(ollama_install_status(PolishOptions.from_env()))


def get_ollama_pull_status(h) -> None:
    parsed = urlparse(h.path)
    query = parse_qs(parsed.query)
    model = (query.get("model") or [""])[0]
    h._send_json({
        "status": _ollama_pull_status(model) if model else _ollama_pull_status(),
        "pulls": list_all_pulls(),
    })


def get_ai_cache(h) -> None:
    parsed = urlparse(h.path)
    query = parse_qs(parsed.query)
    job_id = (query.get("job_id") or [""])[0]
    if not job_id:
        return h._send_error_json("job_id is required.")
    config = h._config()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    h._send_json({"cache": db.list_ai_cache_for_job(job_id)})


def get_stats(h) -> None:
    config = h._config()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    h._send_json(compute_stats(db))


def get_export_csv(h) -> None:
    from job_agent.analytics import jobs_to_csv

    config = h._config()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    csv_text = jobs_to_csv(db.list_jobs(limit=None))
    body = csv_text.encode("utf-8")
    h.send_response(HTTPStatus.OK)
    h.send_header("Content-Type", "text/csv; charset=utf-8")
    h.send_header("Content-Disposition", 'attachment; filename="job-agent-jobs.csv"')
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)
    return None
