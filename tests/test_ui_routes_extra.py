"""Extra coverage for the dashboard routes and ``route_helpers`` free functions.

Extends the live-server characterization pattern from ``test_ui_server_routes``
(without modifying that file). Two layers:

* Direct unit tests of ``route_helpers`` free functions with a seeded temp DB /
  config — simpler and faster than going through HTTP for pure helpers.
* A live loopback server exercising more GET/POST routes for status + JSON shape,
  with all network / LLM calls mocked.

No real network, LLM, or browser calls are performed.
"""
from __future__ import annotations

import http.client
import json
import re
import threading
from contextlib import closing

import pytest

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.ui import route_helpers as rh
from job_agent.ui.security import TOKEN_HEADER


# ── route_helpers free functions (direct) ────────────────────────────────────


@pytest.fixture
def helper_config(tmp_path, monkeypatch):
    """A config with a seeded DB for direct route_helpers tests."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    config = AppConfig(
        data_dir=data_dir,
        profiles_dir=tmp_path / "profiles",
        outputs_dir=tmp_path / "outputs",
    )
    config.ensure_dirs()
    Database(config.db_path).initialize()
    return config


def test_safe_int_clamps_and_defaults():
    # Arrange / Act / Assert
    assert rh._safe_int("5", default=8) == 5
    assert rh._safe_int("garbage", default=8) == 8
    assert rh._safe_int(999, default=8, maximum=30) == 30
    assert rh._safe_int(-4, default=8, minimum=1) == 1


def test_search_links_returns_grouped_links():
    # Act
    result = rh._search_links({"query": "data scientist", "location": "Paris", "limit": 3})

    # Assert
    assert result["query_count"] >= 1
    assert result["link_count"] >= 1
    assert "generated_at" in result


def test_list_jobs_empty_returns_empty_list(helper_config):
    assert rh._list_jobs(helper_config) == []


def test_list_jobs_returns_seeded_jobs(helper_config):
    # Arrange
    db = Database(helper_config.db_path)
    job = JobListing(title="Data Scientist", company="Acme", source="paste", raw_text="x")
    db.save_job(job)

    # Act
    jobs = rh._list_jobs(helper_config)

    # Assert
    assert [j["id"] for j in jobs] == [job.id]


def test_needs_manual_jobs_carries_reason(helper_config):
    # Arrange — seed a walled job with a NEEDS_MANUAL event.
    db = Database(helper_config.db_path)
    job = JobListing(title="ML Engineer", company="Globex", source="paste", raw_text="y")
    db.save_job(job)
    db.update_job_status(job.id, JobStatus.NEEDS_MANUAL)
    db.log_event(job.id, "NEEDS_MANUAL", {"reason": "reCAPTCHA challenge"})

    # Act
    jobs = rh._needs_manual_jobs(helper_config)

    # Assert
    assert len(jobs) == 1
    assert jobs[0]["needs_manual_reason"] == "reCAPTCHA challenge"


def test_save_jobs_imports_and_dedupes(helper_config):
    # Arrange
    job = JobListing(title="Data Scientist", company="Acme", source="api:remotive",
                     raw_text="z", description="ML role")

    # Act — first save imports, second save dedupes.
    first = rh._save_jobs(helper_config, [job], prepare_packets=False, force_packets=False)
    second = rh._save_jobs(helper_config, [job], prepare_packets=False, force_packets=False)

    # Assert
    assert first["imported"] == 1
    assert second["duplicates"] == 1


def test_enrich_batch_collects_per_job_results(helper_config, monkeypatch):
    # Arrange — mock enrich_job so no network is hit; one ok, one error.
    def _fake_enrich(config, job_id, options):
        if job_id == "boom":
            raise RuntimeError("nope")
        return {"sources": {"rome": "ok"}}
    monkeypatch.setattr(rh, "enrich_job", _fake_enrich)

    # Act
    result = rh._enrich_batch(helper_config, {"job_ids": ["good", "boom"]})

    # Assert
    assert result["count"] == 2
    by_id = {r["job_id"]: r for r in result["results"]}
    assert by_id["good"]["ok"] is True
    assert by_id["boom"]["ok"] is False


def test_resolve_github_handle_sanitizes_and_falls_back(helper_config):
    # Arrange — write a profile with a github_url so the fallback path is used.
    (helper_config.profiles_dir / "candidate_profile.json").write_text(
        json.dumps({"contact": {"github_url": "https://github.com/octocat/"}}),
        encoding="utf-8",
    )

    # Act / Assert — explicit handle wins; otherwise fall back to profile.
    assert rh._resolve_github_handle(helper_config, {"handle": "my-user"}) == "my-user"
    assert rh._resolve_github_handle(helper_config, {}) == "octocat"
    # An invalid handle (illegal chars) is rejected.
    assert rh._resolve_github_handle(helper_config, {"handle": "bad/../handle"}) == ""


def test_file_response_path_rejects_paths_outside_roots(helper_config):
    # Arrange — a file safely inside outputs_dir is allowed.
    safe = helper_config.outputs_dir / "ok.txt"
    safe.write_text("hi", encoding="utf-8")

    # Act / Assert
    assert rh._file_response_path(helper_config, str(safe)) == safe.resolve()
    assert rh._file_response_path(helper_config, "C:/Windows/system.ini") is None
    assert rh._file_response_path(helper_config, str(helper_config.outputs_dir / "missing.txt")) is None


def test_export_internships_returns_workbook_and_count(helper_config):
    # Act
    result = rh._export_internships(helper_config, {})

    # Assert — no submitted internships yet, so count is 0 but a path is returned.
    assert result["count"] == 0
    assert result["workbook"]


# ── live server: extra GET/POST routes ───────────────────────────────────────


@pytest.fixture
def server(monkeypatch, tmp_path):
    """A live dashboard on a random port seeded with one scored job."""
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    config = configured_app()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = JobListing(title="Data Scientist", company="ACME", source="paste", raw_text="x")
    job.fit_score = 80.0
    db.save_job(job)

    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, configured_app())
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, _token(port), job.id
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _token(port: int) -> str:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", "/")
        body = conn.getresponse().read().decode("utf-8")
    match = re.search(r'name="csrf-token" content="([^"]+)"', body)
    assert match, "token not injected into index.html"
    return match.group(1)


def _get(port: int, path: str) -> tuple[int, dict, str]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
    try:
        return resp.status, (json.loads(raw) if raw else {}), raw
    except json.JSONDecodeError:
        return resp.status, {}, raw


def _post(port: int, token: str, path: str, body: dict) -> tuple[int, dict]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request(
            "POST", path,
            body=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{port}",
                TOKEN_HEADER: token,
            },
        )
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
    return resp.status, (json.loads(raw) if raw else {})


def test_get_stats_returns_dict(server):
    port, _, _ = server
    status, payload, _ = _get(port, "/api/stats")
    assert status == 200
    assert isinstance(payload, dict)


def test_get_export_csv_streams_csv(server):
    port, _, _ = server
    status, _, raw = _get(port, "/api/export-csv")
    assert status == 200
    # CSV header row should include a recognizable column.
    assert "title" in raw.lower() or "company" in raw.lower()


def test_get_ai_status_reports_reachability(server):
    port, _, _ = server
    status, payload, _ = _get(port, "/api/ai-status")
    assert status == 200
    assert "reachable" in payload


def test_get_ai_cache_requires_job_id(server):
    port, _, _ = server
    status, payload, _ = _get(port, "/api/ai-cache")
    assert status == 400
    assert "error" in payload


def test_get_ai_cache_returns_cache_for_job(server):
    port, _, job_id = server
    status, payload, _ = _get(port, f"/api/ai-cache?job_id={job_id}")
    assert status == 200
    assert "cache" in payload


def test_get_cv_studio_shape(server):
    port, _, _ = server
    status, payload, _ = _get(port, "/api/cv-studio")
    assert status == 200
    assert isinstance(payload, dict)


def test_post_search_links_returns_groups(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/search-links",
                            {"query": "data scientist", "location": "Paris", "limit": 3})
    assert status == 200
    assert payload["query_count"] >= 1


def test_post_multi_search_with_mocked_sources(server, monkeypatch):
    # Arrange — mock the aggregate search so no network is hit.
    from job_agent.ui import route_helpers as helpers

    def _fake_all(*a, **k):
        return {"jobs": [], "per_source": {"remotive": 0}, "errors": {}}
    monkeypatch.setattr(helpers, "search_all_free_sources", _fake_all)

    # Act
    port, token, _ = server
    status, payload = _post(port, token, "/api/multi-search",
                            {"query": "data", "save": False, "sources": ["remotive"]})

    # Assert
    assert status == 200
    assert payload["found"] == 0
    assert "per_source" in payload


def test_post_generate_packet_requires_job_id(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/generate-packet", {})
    assert status == 400
    assert "error" in payload


def test_post_ai_summarize_unknown_job_is_404(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/ai-summarize", {"job_id": "missing"})
    assert status == 404


def test_post_status_updates_seeded_job(server):
    port, token, job_id = server
    status, payload = _post(port, token, "/api/status",
                            {"job_id": job_id, "status": "MANUALLY_SUBMITTED"})
    assert status == 200 and payload == {"ok": True}
    _, jobs, _ = _get(port, "/api/jobs?status=MANUALLY_SUBMITTED")
    assert job_id in {j["id"] for j in jobs["jobs"]}


def test_post_without_token_is_forbidden(server):
    port, _, job_id = server
    # No CSRF token header → guard rejects the mutation.
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request(
            "POST", "/api/status",
            body=json.dumps({"job_id": job_id, "status": "SCORED"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
        )
        resp = conn.getresponse()
        resp.read()
    assert resp.status == 403
