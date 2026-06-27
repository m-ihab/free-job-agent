"""Dashboard preflight action and panel wiring."""
from __future__ import annotations

from pathlib import Path


APP_JS = Path("src/job_agent/ui/static/app.js")


def test_dashboard_has_preflight_action_and_panel():
    js = APP_JS.read_text(encoding="utf-8")

    assert 'data-action="preflight"' in js
    assert "async function runPreflight(" in js
    assert 'api("/api/preflight"' in js
    assert "function renderPreflightPanel(" in js
    assert "safe_keywords_to_add" in js
    assert "unsafe_claims_to_avoid" in js
