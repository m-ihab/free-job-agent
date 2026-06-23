"""Round-2 behavioural tests for the dashboard POST route handlers.

These extend the live-loopback-server pattern from ``test_ui_server_routes`` to
the *remaining* uncovered branches of the ``job_agent.ui.routes.post_*`` modules:
validation errors (missing ``job_id``), not-found branches, AI-unavailable
fallbacks, and the success paths that fan out to heavy collaborators. Every
heavy collaborator (generator / LLM / portfolio / cv-studio / pipeline / market
report) is monkeypatched at the route module so no real LLM / LaTeX / network
work runs. Assertions lock in HTTP status + JSON shape.
"""
from __future__ import annotations

import http.client
import json
import re
import threading
from contextlib import closing

import pytest

from job_agent.schemas.job import JobListing
from job_agent.ui.security import TOKEN_HEADER


@pytest.fixture
def server(monkeypatch, tmp_path):
    """A live dashboard on a random port seeded with one job.

    Yields ``(port, token, job_id)``.
    """
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.db.database import Database
    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    config = configured_app()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = JobListing(title="Data Scientist", company="ACME", source="paste", raw_text="x")
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


def _post(port: int, token: str, path: str, body: dict) -> tuple[int, dict]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request(
            "POST",
            path,
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


# ── post_search: validation + success (mocked collaborators) ─────────────────

def test_generate_packet_requires_job_id(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/generate-packet", {})
    assert status == 400
    assert "error" in payload


def test_generate_packet_success_returns_packet_dict(server, monkeypatch):
    # Arrange: stub the pipeline + serializer so no LaTeX/LLM runs.
    from job_agent.ui.routes import post_search

    sentinel = object()
    monkeypatch.setattr(post_search, "generate_packet_for_job", lambda *a, **k: sentinel)
    monkeypatch.setattr(post_search, "packet_to_dict", lambda packet: {"id": "pkt-1"})
    port, token, job_id = server

    # Act
    status, payload = _post(port, token, "/api/generate-packet", {"job_id": job_id})

    # Assert
    assert status == 200
    assert payload == {"packet": {"id": "pkt-1"}}


def test_add_text_requires_text(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/add-text", {"text": "   "})
    assert status == 400
    assert "error" in payload


def test_add_text_success_reports_created(server, monkeypatch):
    from job_agent.ui.routes import post_search

    job = JobListing(title="Pasted", company="X", source="paste", raw_text="z")
    monkeypatch.setattr(post_search, "add_text_job", lambda *a, **k: (job, True))
    monkeypatch.setattr(post_search, "job_to_dict", lambda *a, **k: {"id": job.id})
    port, token, _ = server

    status, payload = _post(port, token, "/api/add-text", {"text": "Some job text"})
    assert status == 200
    assert payload["created"] is True
    assert payload["job"] == {"id": job.id}


def test_enrich_requires_job_id(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/enrich", {})
    assert status == 400
    assert "error" in payload


def test_enrich_github_requires_handle(server, monkeypatch):
    from job_agent.ui.routes import post_search

    monkeypatch.setattr(post_search, "_resolve_github_handle", lambda *a, **k: "")
    port, token, _ = server
    status, payload = _post(port, token, "/api/enrich-github", {})
    assert status == 400
    assert "error" in payload


def test_import_cv_template_requires_filename_and_content(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/import-cv-template", {"filename": "cv.tex"})
    assert status == 400
    assert "error" in payload


def test_multi_search_aggregates_mocked_sources(server, monkeypatch):
    from job_agent.ui import route_helpers

    captured: dict = {}

    def fake_search_all(**kwargs):
        captured.update(kwargs)
        return {"jobs": [], "per_source": {"remoteok": 0}, "errors": {}}

    monkeypatch.setattr(route_helpers, "search_all_free_sources", fake_search_all)
    port, token, _ = server

    status, payload = _post(
        port, token, "/api/multi-search",
        {"query": "ml", "sources": "remoteok, weworkremotely", "save": False},
    )
    assert status == 200
    assert payload["found"] == 0
    assert payload["sources"] == ["remoteok", "weworkremotely"]
    assert payload["per_source"] == {"remoteok": 0}


# ── post_generate: validation + success ──────────────────────────────────────

def test_generate_outreach_requires_job_id(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/generate-outreach", {})
    assert status == 400
    assert "error" in payload


def test_generate_outreach_not_found_for_unknown_job(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/generate-outreach", {"job_id": "nope"})
    assert status == 400
    assert payload["error"] == "Job not found."


def test_generate_outreach_success_returns_email(server, monkeypatch):
    from job_agent.ui.routes import post_generate

    monkeypatch.setattr(post_generate, "load_profile_bundle", lambda config: (object(), object(), None))
    monkeypatch.setattr(post_generate, "generate_outreach_email", lambda *a, **k: "Dear recruiter")
    port, token, job_id = server

    status, payload = _post(port, token, "/api/generate-outreach", {"job_id": job_id})
    assert status == 200
    assert payload["email_md"] == "Dear recruiter"


def test_linkedin_message_requires_job_id(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/linkedin-message", {})
    assert status == 400
    assert "error" in payload


def test_linkedin_message_connect_branch(server, monkeypatch):
    from job_agent.ui.routes import post_generate

    monkeypatch.setattr(post_generate, "load_profile_bundle", lambda config: (object(), object(), None))
    monkeypatch.setattr(post_generate, "generate_linkedin_connect_request", lambda *a, **k: "Hi connect")
    port, token, job_id = server

    status, payload = _post(
        port, token, "/api/linkedin-message", {"job_id": job_id, "type": "connect"}
    )
    assert status == 200
    # No Ollama in the test env → the engine selector returns the deterministic
    # draft and reports the "standard" engine.
    assert payload == {"message": "Hi connect", "type": "connect", "engine": "standard"}


def test_interview_prep_requires_job_id(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/interview-prep", {})
    assert status == 400
    assert "error" in payload


def test_followup_email_not_found(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/followup-email", {"job_id": "ghost"})
    assert status == 400
    assert payload["error"] == "Job not found."


def test_market_report_success_shape(server, monkeypatch):
    from job_agent.ui.routes import post_generate

    class _Profile:
        def all_skill_names(self):
            return ["python"]

    class _Report:
        total_jobs = 1
        top_skills = [("python", 1)]
        contract_breakdown = {"CDI": 1}
        language_requirement_pct = 50.0
        remote_pct = 25.0
        your_match_rate = 80.0

        def to_markdown(self):
            return "# Market"

    monkeypatch.setattr(post_generate, "load_profile_bundle", lambda config: (_Profile(), object(), None))
    monkeypatch.setattr(post_generate, "build_market_report", lambda *a, **k: _Report())
    port, token, _ = server

    status, payload = _post(port, token, "/api/market-report", {})
    assert status == 200
    assert payload["total_jobs"] == 1
    assert payload["french_pct"] == 50
    assert payload["markdown"] == "# Market"


def test_headhunter_strategy_returns_report_md(server, monkeypatch):
    from job_agent.ui.routes import post_generate

    monkeypatch.setattr(post_generate, "english_first_strategy_report", lambda jobs: "## Strategy")
    port, token, _ = server

    status, payload = _post(port, token, "/api/headhunter-strategy", {})
    assert status == 200
    assert payload == {"report_md": "## Strategy"}


def test_coach_plan_success(server, monkeypatch):
    from job_agent.ui.routes import post_generate

    monkeypatch.setattr(post_generate, "_coach_plan", lambda config: {"plan": "do this"})
    port, token, _ = server

    status, payload = _post(port, token, "/api/coach-plan", {})
    assert status == 200
    assert payload == {"plan": "do this"}


# ── post_ai: validation, not-found, unavailable, success ─────────────────────

def test_ai_chat_requires_job_id_and_question(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/ai-chat", {"job_id": "x"})
    assert status == 400
    assert "error" in payload


def test_ai_chat_not_found_returns_404(server):
    port, token, _ = server
    status, payload = _post(
        port, token, "/api/ai-chat", {"job_id": "ghost", "question": "hi?"}
    )
    assert status == 404
    assert payload["error"] == "Job not found."


def test_ai_chat_unavailable_returns_503(server, monkeypatch):
    from job_agent.ui.routes import post_ai

    monkeypatch.setattr(post_ai, "load_profile_bundle", lambda config: (object(), object(), None))
    monkeypatch.setattr(post_ai, "_ai_chat_about_job", lambda *a, **k: "")
    port, token, job_id = server

    status, payload = _post(
        port, token, "/api/ai-chat", {"job_id": job_id, "question": "Tell me?"}
    )
    assert status == 503
    assert "error" in payload


def test_ai_chat_success_returns_reply(server, monkeypatch):
    from job_agent.ui.routes import post_ai

    monkeypatch.setattr(post_ai, "load_profile_bundle", lambda config: (object(), object(), None))
    monkeypatch.setattr(post_ai, "_ai_chat_about_job", lambda *a, **k: "Here is my reply")
    port, token, job_id = server

    status, payload = _post(
        port, token, "/api/ai-chat", {"job_id": job_id, "question": "Tell me?"}
    )
    assert status == 200
    assert payload == {"reply": "Here is my reply"}


def test_ai_summarize_requires_job_id(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/ai-summarize", {})
    assert status == 400
    assert "error" in payload


def test_ai_summarize_unavailable_returns_503(server, monkeypatch):
    from job_agent.ui.routes import post_ai

    monkeypatch.setattr(post_ai, "_ai_summarize_job", lambda job: "")
    port, token, job_id = server

    status, payload = _post(port, token, "/api/ai-summarize", {"job_id": job_id})
    assert status == 503


def test_ai_summarize_success_caches_and_returns(server, monkeypatch):
    from job_agent.ui.routes import post_ai

    monkeypatch.setattr(post_ai, "_ai_summarize_job", lambda job: "TL;DR text")
    monkeypatch.setattr(post_ai, "resolve_ollama_model", lambda: "llama3.2:3b")
    port, token, job_id = server

    status, payload = _post(port, token, "/api/ai-summarize", {"job_id": job_id})
    assert status == 200
    assert payload == {"summary": "TL;DR text"}


def test_ai_classify_unavailable_returns_503(server, monkeypatch):
    from job_agent.ui.routes import post_ai

    monkeypatch.setattr(post_ai, "_ai_classify_job", lambda job: None)
    port, token, job_id = server

    status, payload = _post(port, token, "/api/ai-classify", {"job_id": job_id})
    assert status == 503


def test_ai_analyze_unavailable_returns_503(server, monkeypatch):
    from job_agent.ui.routes import post_ai

    monkeypatch.setattr(post_ai, "load_profile_bundle", lambda config: (object(), object(), None))
    monkeypatch.setattr(post_ai, "_ai_analyze_fit", lambda *a, **k: None)
    port, token, job_id = server

    status, payload = _post(port, token, "/api/ai-analyze", {"job_id": job_id})
    assert status == 503


def test_ai_plan_queries_success(server, monkeypatch):
    from job_agent.ui.routes import post_ai

    monkeypatch.setattr(post_ai, "load_profile_bundle", lambda config: (object(), object(), None))
    monkeypatch.setattr(post_ai, "suggest_search_queries", lambda *a, **k: {"queries": ["ds paris"]})
    port, token, _ = server

    status, payload = _post(port, token, "/api/ai-plan-queries", {"seed_query": "ds"})
    assert status == 200
    assert payload == {"queries": ["ds paris"]}


def test_ollama_pull_uses_default_model(server, monkeypatch):
    from job_agent.ui.routes import post_ai

    captured: dict = {}

    def fake_pull(model, opts):
        captured["model"] = model
        return {"ok": True, "model": model}

    monkeypatch.setattr(post_ai, "_pull_ollama_model", fake_pull)
    port, token, _ = server

    status, payload = _post(port, token, "/api/ollama-pull", {"model": "  "})
    assert status == 200
    assert captured["model"] == "llama3.2:3b"


# ── post_cv_studio: deterministic ops (mocked compile where needed) ──────────

def test_cv_studio_reorder_returns_rewritten_text(server, monkeypatch):
    from job_agent.ui.routes import post_cv_studio

    monkeypatch.setattr(post_cv_studio, "_studio_reorder", lambda text, order: "REORDERED")
    port, token, _ = server

    status, payload = _post(
        port, token, "/api/cv-studio/reorder", {"text": "x", "order": ["a", "b"]}
    )
    assert status == 200
    assert payload == {"ok": True, "text": "REORDERED"}


def test_cv_studio_language_success(server, monkeypatch):
    from job_agent.ui.routes import post_cv_studio

    monkeypatch.setattr(post_cv_studio, "_studio_set_language", lambda config, lang: {"ok": True, "language": lang})
    port, token, _ = server

    status, payload = _post(port, token, "/api/cv-studio/language", {"language": "FR"})
    assert status == 200
    assert payload == {"ok": True, "language": "fr"}


def test_cv_studio_swap_sections_passes_labels(server, monkeypatch):
    from job_agent.ui.routes import post_cv_studio

    captured: dict = {}

    def fake_swap(config, a, b):
        captured["a"], captured["b"] = a, b
        return {"ok": True}

    monkeypatch.setattr(post_cv_studio, "_studio_swap_sections", fake_swap)
    port, token, _ = server

    status, payload = _post(
        port, token, "/api/cv-studio/swap-sections", {"first": "Education", "second": "Skills"}
    )
    assert status == 200
    assert captured == {"a": "Education", "b": "Skills"}


def test_cv_studio_asset_save_validation_error(server, monkeypatch):
    from job_agent.ui.routes import post_cv_studio

    def fake_write(config, name, text):
        raise ValueError("bad asset name")

    monkeypatch.setattr(post_cv_studio, "_studio_write_asset", fake_write)
    port, token, _ = server

    status, payload = _post(
        port, token, "/api/cv-studio/asset-save", {"name": "../evil", "text": "x"}
    )
    assert status == 400
    assert payload["error"] == "bad asset name"


def test_cv_studio_single_page_check_calls_guard(server, monkeypatch):
    from job_agent.ui.routes import post_cv_studio

    monkeypatch.setattr(
        post_cv_studio, "_studio_single_page",
        lambda config, text: {"ok": True, "single_page": True, "echoed": text},
    )
    port, token, _ = server

    status, payload = _post(port, token, "/api/cv-studio/single-page-check", {"text": "draft"})
    assert status == 200
    assert payload["echoed"] == "draft"


def test_cv_studio_ats_keywords_success(server, monkeypatch):
    from job_agent.ui.routes import post_cv_studio

    monkeypatch.setattr(
        post_cv_studio, "_studio_ats_radar",
        lambda config, text, role: {"ok": True, "role": role, "coverage": 42},
    )
    port, token, _ = server

    status, payload = _post(
        port, token, "/api/cv-studio/ats-keywords", {"text": "cv", "role": "ml_engineer"}
    )
    assert status == 200
    assert payload["role"] == "ml_engineer"


def test_cv_studio_compile_calls_preview(server, monkeypatch):
    from job_agent.ui.routes import post_cv_studio

    monkeypatch.setattr(
        post_cv_studio, "_studio_compile_preview",
        lambda config, text: {"ok": False, "reason": "no_source"},
    )
    port, token, _ = server

    status, payload = _post(port, token, "/api/cv-studio/compile", {})
    assert status == 200
    assert payload == {"ok": False, "reason": "no_source"}


# ── post_portfolio: success + validation ─────────────────────────────────────

def test_portfolio_generate_success(server, monkeypatch):
    from job_agent.ui.routes import post_portfolio

    monkeypatch.setattr(
        post_portfolio, "_portfolio_generate",
        lambda config, **k: {"html": "<html></html>", "css": "body{}"},
    )
    port, token, _ = server

    status, payload = _post(port, token, "/api/portfolio/generate", {"theme": "signal"})
    assert status == 200
    assert payload["html"].startswith("<html>")


def test_portfolio_github_repos_requires_handle(server, monkeypatch):
    from job_agent.ui.routes import post_portfolio

    monkeypatch.setattr(post_portfolio, "_resolve_github_handle", lambda config, payload: "")
    port, token, _ = server

    status, payload = _post(port, token, "/api/portfolio/github-repos", {})
    assert status == 400
    assert "error" in payload


def test_portfolio_github_repos_success(server, monkeypatch):
    from job_agent.ui.routes import post_portfolio

    monkeypatch.setattr(post_portfolio, "_resolve_github_handle", lambda config, payload: "octocat")
    monkeypatch.setattr(post_portfolio, "_portfolio_github_repos", lambda handle, limit: [{"name": "repo"}])
    port, token, _ = server

    status, payload = _post(port, token, "/api/portfolio/github-repos", {"handle": "octocat"})
    assert status == 200
    assert payload["handle"] == "octocat"
    assert payload["repos"] == [{"name": "repo"}]


def test_portfolio_save_passes_html_css(server, monkeypatch):
    from job_agent.ui.routes import post_portfolio

    captured: dict = {}

    def fake_save(config, html, css):
        captured["html"], captured["css"] = html, css
        return {"ok": True}

    monkeypatch.setattr(post_portfolio, "_portfolio_save", fake_save)
    port, token, _ = server

    status, payload = _post(
        port, token, "/api/portfolio/save", {"html": "<h1>", "css": ".a{}"}
    )
    assert status == 200
    assert captured == {"html": "<h1>", "css": ".a{}"}


# ── post_autopilot: validation + delegation ──────────────────────────────────

def test_delete_job_requires_job_id(server):
    port, token, _ = server
    status, payload = _post(port, token, "/api/delete-job", {})
    assert status == 400
    assert "error" in payload


def test_auto_apply_confirm_delegates(server, monkeypatch):
    from job_agent.ui.routes import post_autopilot

    monkeypatch.setattr(post_autopilot._auto_apply, "confirm", lambda: {"ok": True, "action": "confirm"})
    port, token, _ = server

    status, payload = _post(port, token, "/api/auto-apply/confirm", {})
    assert status == 200
    assert payload == {"ok": True, "action": "confirm"}


def test_auto_apply_start_delegates_with_params(server, monkeypatch):
    from job_agent.ui.routes import post_autopilot

    captured: dict = {}

    def fake_start(config, mode, min_score, limit, job_ids=None):
        captured.update(mode=mode, min_score=min_score, limit=limit, job_ids=job_ids)
        return {"ok": True}

    monkeypatch.setattr(post_autopilot._auto_apply, "start", fake_start)
    port, token, _ = server

    status, payload = _post(
        port, token, "/api/auto-apply/start",
        {"mode": "full_auto", "min_score": 80, "limit": 3, "job_ids": ["a", "b"]},
    )
    assert status == 200
    assert captured["mode"] == "full_auto"
    assert captured["limit"] == 3
    assert captured["job_ids"] == ["a", "b"]


def test_maintenance_dedupe_dry_run(server, monkeypatch):
    from job_agent.ui.routes import post_autopilot

    captured: dict = {}

    def fake_dedupe(config, dry_run):
        captured["dry_run"] = dry_run
        return {"ok": True, "removed": 0}

    monkeypatch.setattr(post_autopilot, "_dedupe_jobs", fake_dedupe)
    port, token, _ = server

    status, payload = _post(port, token, "/api/maintenance/dedupe", {"dry_run": True})
    assert status == 200
    assert captured["dry_run"] is True
