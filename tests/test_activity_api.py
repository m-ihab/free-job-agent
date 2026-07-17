"""Cross-job activity feed coverage for the local dashboard."""
from __future__ import annotations

import http.client
import json
import threading
from contextlib import closing

import pytest

from job_agent.db.database import Database
from job_agent.schemas.job import JobListing


@pytest.fixture
def activity_server(tmp_path, monkeypatch, server_ready):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    db = Database(data_dir / "jobs.db")
    db.initialize()
    db.save_job(JobListing(id="activity-a", title="ML Engineer", company="Alpha"))
    db.save_job(JobListing(id="activity-b", title="Data Scientist", company="Beta"))

    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, configured_app())
    port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    server_ready("127.0.0.1", port)
    try:
        yield port, db
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(port: int, path: str) -> tuple[int, dict[str, object]]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", path)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
    return response.status, json.loads(raw)


def test_activity_feed_is_newest_first_and_keeps_failures_and_handoffs(
    activity_server,
) -> None:
    port, db = activity_server
    db.log_event("activity-a", "JOB_ADDED", {"source": "paste"})
    db.log_event("activity-b", "FILTER_FAILED", {"reasons": ["French required"]})
    db.log_event("activity-a", "NEEDS_MANUAL", {"reason": "CAPTCHA detected"})
    db.log_event("activity-b", "AUTO_APPLY_ERROR", {"error": "Browser closed"})
    db.log_event(None, "SYSTEM_ERROR", {"error": "Worker stopped"})

    status, payload = _get(port, "/api/activity")

    assert status == 200
    events = payload["events"]
    assert isinstance(events, list)
    assert [row["event_type"] for row in events] == [
        "SYSTEM_ERROR",
        "AUTO_APPLY_ERROR",
        "NEEDS_MANUAL",
        "FILTER_FAILED",
        "JOB_ADDED",
    ]
    assert "error" in events[0]["message"].casefold()
    assert "error" in events[1]["message"].casefold()
    assert "manual" in events[2]["message"].casefold()
    assert "failed" in events[3]["message"].casefold()
    assert set(events[0]) == {
        "id",
        "job_id",
        "event_type",
        "subsystem",
        "message",
        "created_at",
    }


def test_activity_feed_filters_by_subsystem_before_applying_200_row_cap(
    activity_server,
) -> None:
    port, db = activity_server
    db.log_event("activity-a", "NEEDS_MANUAL", {"reason": "Login wall"})
    for index in range(205):
        db.log_event(
            "activity-b",
            "STATUS_CHANGED",
            {"new_status": "SCORED", "note": f"change {index}"},
        )

    all_status, all_payload = _get(port, "/api/activity")
    apply_status, apply_payload = _get(port, "/api/activity?subsystem=apply")

    assert all_status == apply_status == 200
    assert len(all_payload["events"]) == 200
    assert all_payload["events"][0]["message"].endswith("change 204.")
    assert [row["event_type"] for row in apply_payload["events"]] == ["NEEDS_MANUAL"]
    assert apply_payload["subsystem"] == "apply"


def test_activity_feed_rejects_unknown_subsystem(activity_server) -> None:
    port, _db = activity_server

    status, payload = _get(port, "/api/activity?subsystem=made-up")

    assert status == 400
    assert "subsystem" in str(payload["error"]).casefold()
