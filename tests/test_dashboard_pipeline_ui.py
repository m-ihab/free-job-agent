"""Dashboard Pipeline cockpit wiring."""
from __future__ import annotations

from pathlib import Path


INDEX_HTML = Path("src/job_agent/ui/static/index.html")
PIPELINE_JS = Path("src/job_agent/ui/static/pipeline.js")
APP_JS = Path("src/job_agent/ui/static/app.js")


def test_dashboard_has_pipeline_tab_and_script():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'data-tab="pipeline"' in html
    assert 'id="tab-pipeline"' in html
    assert '/static/pipeline.js' in html


def test_pipeline_js_uses_pipeline_routes():
    js = PIPELINE_JS.read_text(encoding="utf-8")

    assert "/api/pipeline/today" in js
    assert "/api/pipeline/stale" in js
    assert "/api/pipeline/metrics" in js
    assert "/api/job-notes" in js
    assert "/api/contacts" in js
    assert "/api/referrals" in js
    assert "/api/referral-ask" in js


def test_app_loads_pipeline_tab_hook():
    js = APP_JS.read_text(encoding="utf-8")

    assert "JobAgentPipeline" in js
