"""POST handlers for the pipeline / conversion cockpit."""
from __future__ import annotations

from job_agent.conversion import next_best_action, set_job_notes
from job_agent.db.database import Database
from job_agent.ui.route_helpers import _tracker


def post_next_action(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        return h._send_error_json("job_id is required.")
    job = _tracker(config).get_job(job_id)
    if not job:
        return h._send_error_json("Job not found.")
    h._send_json({"action": next_best_action(job, config).__dict__})


def post_job_notes(h, payload) -> None:
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        return h._send_error_json("job_id is required.")
    notes = str(payload.get("notes") or "")
    try:
        set_job_notes(h._config(), job_id, notes)
    except ValueError as exc:
        return h._send_error_json(str(exc))
    h._send_json({"job_id": job_id, "notes": notes})


def post_followup_done(h, payload) -> None:
    try:
        task_id = int(payload.get("task_id") or 0)
    except (TypeError, ValueError):
        task_id = 0
    if task_id <= 0:
        return h._send_error_json("task_id is required.")
    db = Database(h._config().db_path)  # type: ignore[arg-type]
    db.initialize()
    if not db.complete_followup_task(task_id):
        return h._send_error_json("Follow-up task not found.")
    h._send_json({"ok": True, "task_id": task_id})
