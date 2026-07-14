"""POST handler for local thumbs feedback."""

from __future__ import annotations

from typing import Any

from job_agent.feedback import aggregate_feedback, calculate_feedback_adjustment, record_feedback
from job_agent.ui.route_helpers import _tracker


def post_feedback(h: Any, payload: dict[str, Any]) -> None:
    tracker = _tracker(h._config())
    job_id = str(payload.get("job_id") or "").strip()
    verdict = str(payload.get("verdict") or "").strip().casefold()
    if not job_id:
        return h._send_error_json("job_id is required.")
    try:
        feedback = record_feedback(tracker.db, job_id, verdict)
    except ValueError as exc:
        return h._send_error_json(str(exc))
    job = tracker.get_job(feedback.job_id)
    assert job is not None
    base_score = float(job.fit_score or 0)
    adjustment = calculate_feedback_adjustment(
        job,
        aggregate_feedback(tracker.db.list_feedback()),
        base_score=base_score,
    )
    h._send_json({"feedback": feedback.to_dict(), "adjustment": adjustment.to_dict()})
