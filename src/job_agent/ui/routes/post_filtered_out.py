"""Mutating operations for persisted filtered-out jobs."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from job_agent.schemas.job import JobStatus
from job_agent.ui.route_helpers import _tracker


def post_filtered_out_action(h: Any, payload: dict[str, Any]) -> None:
    """Restore a filtered job to the queue or delete it through the tracker."""
    job_id = str(payload.get("job_id") or "").strip()
    action = str(payload.get("action") or "").strip().casefold()
    if not job_id:
        return h._send_error_json("job_id is required.", HTTPStatus.BAD_REQUEST)
    if action not in {"restore", "delete"}:
        return h._send_error_json(
            "action must be 'restore' or 'delete'.", HTTPStatus.BAD_REQUEST
        )

    tracker = _tracker(h._config())
    job = tracker.get_job(job_id)
    if job is None:
        return h._send_error_json(
            f"Job not found: {job_id}", HTTPStatus.NOT_FOUND
        )

    if action == "delete":
        deleted_id = tracker.delete_job(
            job.id, note="Deleted from filtered-out dashboard"
        )
        return h._send_json(
            {"ok": True, "action": action, "job_id": deleted_id}
        )

    changed = job.status is JobStatus.FILTERED
    if changed:
        tracker.update_status(
            job.id, JobStatus.NEW, note="Restored from filtered-out dashboard"
        )
    h._send_json(
        {"ok": True, "action": action, "job_id": job.id, "changed": changed}
    )
