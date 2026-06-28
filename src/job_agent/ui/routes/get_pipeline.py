"""GET handlers for the pipeline / conversion cockpit."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from job_agent.conversion import (
    build_today_queue,
    conversion_metrics,
    detect_stale,
    get_job_notes,
)
from job_agent.ui.route_helpers import _safe_int, _tracker


def get_pipeline_today(h) -> None:
    config = h._config()
    parsed = urlparse(h.path)
    query = parse_qs(parsed.query)
    limit = _safe_int((query.get("limit") or ["10"])[0], 10, minimum=1, maximum=50)
    jobs = _tracker(config).list_jobs(limit=None)
    h._send_json({"items": [item.__dict__ for item in build_today_queue(jobs, config, limit=limit)]})


def get_pipeline_stale(h) -> None:
    config = h._config()
    jobs = _tracker(config).list_jobs(limit=None)
    h._send_json({"jobs": [item.__dict__ for item in detect_stale(jobs, config)]})


def get_pipeline_metrics(h) -> None:
    config = h._config()
    jobs = _tracker(config).list_jobs(limit=None)
    h._send_json(conversion_metrics(jobs).to_dict())


def get_job_notes_route(h) -> None:
    parsed = urlparse(h.path)
    query = parse_qs(parsed.query)
    job_id = (query.get("job_id") or [""])[0]
    if not job_id:
        return h._send_error_json("job_id is required.")
    try:
        h._send_json({"job_id": job_id, "notes": get_job_notes(h._config(), job_id)})
    except ValueError as exc:
        h._send_error_json(str(exc))
