"""Dashboard preflight action and panel wiring."""
from __future__ import annotations

from pathlib import Path


STATIC_DIR = Path("src/job_agent/ui/static")


def _dashboard_js() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(STATIC_DIR.glob("*.js"))
    )


def test_dashboard_has_preflight_action_and_panel():
    js = _dashboard_js()

    assert 'data-action="preflight"' in js
    assert "async function runPreflight(" in js
    assert 'api("/api/preflight"' in js
    assert "function renderPreflightPanel(" in js
    assert "safe_keywords_to_add" in js
    assert "unsafe_claims_to_avoid" in js
