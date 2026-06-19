"""POST handlers for autopilot, auto-apply, maintenance and job-status routes."""
from __future__ import annotations

from job_agent.autopilot import AutopilotConfig, get_autopilot
from job_agent.maintenance import (
    clear_broken_sources as _clear_broken_sources,
    dedupe_jobs as _dedupe_jobs,
    rescan_companies as _rescan_companies,
    validate_cac40_sources as _validate_cac40_sources,
)
from job_agent.schemas.job import JobStatus
from job_agent import auto_apply as _auto_apply
from job_agent.ui.route_helpers import _safe_int, _tracker


def post_autopilot_start(h, payload) -> None:
    config = h._config()
    autopilot_options = AutopilotConfig(
        queries=[q.strip() for q in (payload.get("queries") or []) if str(q).strip()] or AutopilotConfig().queries,
        location=str(payload.get("location") or "Paris"),
        language=str(payload.get("language") or "both"),
        interval_minutes=int(payload.get("interval_minutes") or 30),
        auto_packet_threshold=int(payload.get("auto_packet_threshold") or 75),
        multi_source_limit=int(payload.get("multi_source_limit") or 8),
        france_travail_limit=int(payload.get("france_travail_limit") or 15),
        radius_km=_safe_int(payload.get("radius_km"), 25, minimum=0, maximum=100),
        min_relevance=_safe_int(payload.get("min_relevance"), 20, minimum=0, maximum=100),
        france_eu_only=bool(payload.get("france_eu_only", True)),
        use_france_travail=bool(payload.get("use_france_travail", True)),
        use_multi_source=bool(payload.get("use_multi_source", True)),
        max_packets_per_cycle=int(payload.get("max_packets_per_cycle") or 5),
        contract_type=str(payload.get("contract_type") or "stage_and_alternance"),
        email_notify=bool(payload.get("email_notify", False)),
        auto_apply=bool(payload.get("auto_apply", False)),
        auto_apply_mode=str(payload.get("auto_apply_mode") or "fill_and_confirm"),
        auto_apply_min_score=int(payload.get("auto_apply_min_score") or 75),
    )
    state = get_autopilot(config).start(autopilot_options)
    h._send_json({"state": state.__dict__, "status": get_autopilot(config).status()})


def post_autopilot_stop(h, payload) -> None:
    config = h._config()
    state = get_autopilot(config).stop()
    h._send_json({"state": state.__dict__, "status": get_autopilot(config).status()})


def post_maintenance_rescan_companies(h, payload) -> None:
    dry = bool(payload.get("dry_run"))
    h._send_json(_rescan_companies(h._config(), dry_run=dry))


def post_maintenance_dedupe(h, payload) -> None:
    dry = bool(payload.get("dry_run"))
    h._send_json(_dedupe_jobs(h._config(), dry_run=dry))


def post_maintenance_validate_sources(h, payload) -> None:
    h._send_json(_validate_cac40_sources(h._config()))


def post_maintenance_clear_broken(h, payload) -> None:
    h._send_json(_clear_broken_sources(h._config()))


def post_status(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    status = JobStatus(str(payload.get("status") or ""))
    tracker = _tracker(config)
    tracker.update_status(job_id, status, note=str(payload.get("note") or ""))
    h._send_json({"ok": True})


def post_delete_job(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        return h._send_error_json("job_id is required.")
    tracker = _tracker(config)
    deleted_id = tracker.delete_job(job_id, note=str(payload.get("note") or "Dashboard removal"))
    h._send_json({"ok": True, "deleted_id": deleted_id})


def post_auto_apply_start(h, payload) -> None:
    config = h._config()
    mode = str(payload.get("mode") or "fill_and_confirm")
    min_score = float(payload.get("min_score") or 70)
    limit = _safe_int(payload.get("limit"), 10, minimum=1, maximum=50)
    job_ids_raw = payload.get("job_ids")
    job_ids = [str(j) for j in job_ids_raw] if isinstance(job_ids_raw, list) and job_ids_raw else None
    h._send_json(_auto_apply.start(config, mode, min_score, limit, job_ids=job_ids))


def post_auto_apply_confirm(h, payload) -> None:
    h._send_json(_auto_apply.confirm())


def post_auto_apply_skip(h, payload) -> None:
    h._send_json(_auto_apply.skip())


def post_auto_apply_cancel(h, payload) -> None:
    h._send_json(_auto_apply.cancel())


def post_auto_apply_open_browser(h, payload) -> None:
    h._send_json(_auto_apply.open_browser_for_login(h._config()))
