from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, PacketStatus


@pytest.fixture
def metrics_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    server_ready: Callable[[str, int], None],
) -> Iterator[tuple[int, Database]]:
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    config = configured_app()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, config)
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


def _seed_metrics(db: Database) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    specs = [
        ("added", JobStatus.NEW, "manual", None, 5),
        ("scored", JobStatus.SCORED, "api:remoteok", 45, 4),
        ("packet", JobStatus.PACKET_READY, "remoteok", 62, 3),
        ("applied", JobStatus.APPLIED, "manual", 74, 2),
        ("response", JobStatus.REJECTED, "manual", 88, 1),
        ("interview", JobStatus.INTERVIEWING, "api:remoteok", 92, 0),
    ]
    jobs: dict[str, JobListing] = {}
    for key, status, source, score, days_ago in specs:
        stamp = (now - timedelta(days=days_ago)).isoformat()
        job = JobListing(
            title=key.title(),
            company="Example",
            source=source,
            status=status,
            fit_score=score,
            created_at=stamp,
            updated_at=stamp,
        )
        db.save_job(job)
        jobs[key] = job
    db.save_packet(
        ApplicationPacket(
            job_id=jobs["packet"].id,
            status=PacketStatus.READY,
            fit_score=62,
        )
    )


def _get_json(port: int, path: str) -> tuple[int, dict]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", path)
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
    return response.status, payload


def test_get_metrics_returns_seeded_dashboard_counts(metrics_server: tuple[int, Database]) -> None:
    port, db = metrics_server
    _seed_metrics(db)

    status, payload = _get_json(port, "/api/metrics")

    assert status == 200
    assert {
        "funnel",
        "sources",
        "score_distribution",
        "applications_over_time",
        "status_now",
        "kpis",
        "generated_at",
    } <= payload.keys()
    assert {row["key"]: row["count"] for row in payload["funnel"]} == {
        "added": 6,
        "scored": 5,
        "packet": 4,
        "applied": 3,
        "response": 2,
        "interview": 1,
    }
    assert payload["kpis"] == {
        "tracked": 6,
        "scored": 5,
        "packets": 4,
        "applied": 3,
        "responses": 2,
        "interviews": 1,
        "application_rate": 50.0,
        "response_rate": 66.7,
        "interview_rate": 33.3,
    }
    sources = {row["source"]: row for row in payload["sources"]}
    assert sources["manual"] == {
        "source": "manual",
        "count": 3,
        "applications": 2,
        "conversion_rate": 66.7,
    }
    assert sources["remoteok"] == {
        "source": "remoteok",
        "count": 3,
        "applications": 1,
        "conversion_rate": 33.3,
    }
    assert [row["count"] for row in payload["score_distribution"]] == [1, 1, 1, 2]
    assert len(payload["applications_over_time"]) == 60
    assert sum(row["count"] for row in payload["applications_over_time"]) == 3
    statuses = {row["status"]: row["count"] for row in payload["status_now"]}
    assert statuses["INTERVIEWING"] == 1
    assert statuses["REJECTED"] == 1


def test_get_metrics_has_honest_empty_shapes(metrics_server: tuple[int, Database]) -> None:
    port, _ = metrics_server

    status, payload = _get_json(port, "/api/metrics")

    assert status == 200
    assert [row["count"] for row in payload["funnel"]] == [0, 0, 0, 0, 0, 0]
    assert payload["sources"] == []
    assert [row["count"] for row in payload["score_distribution"]] == [0, 0, 0, 0]
    assert len(payload["applications_over_time"]) == 60
    assert all(row["count"] == 0 for row in payload["applications_over_time"])
    assert payload["status_now"] == []


def test_dashboard_serves_local_pwa_manifest(metrics_server: tuple[int, Database]) -> None:
    port, _ = metrics_server

    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", "/manifest.webmanifest")
        response = conn.getresponse()
        body = response.read().decode("utf-8")

    assert response.status == 200
    assert response.getheader("Content-Type") == "application/manifest+json"
    assert json.loads(body)["start_url"] == "/"
