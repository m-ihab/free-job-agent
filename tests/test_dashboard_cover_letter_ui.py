"""Dashboard cover-letter on-demand wiring."""
from __future__ import annotations

from pathlib import Path


STATIC_DIR = Path("src/job_agent/ui/static")
INDEX_HTML = Path("src/job_agent/ui/static/index.html")
ROUTES = Path("src/job_agent/ui/routes/__init__.py")


def _dashboard_js() -> str:
    # app.js plus the R3-extracted modules — wiring may live in any of them.
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(STATIC_DIR.glob("*.js"))
    )


def test_dashboard_has_generate_letter_action():
    js = _dashboard_js()

    assert 'data-action="cover-letter"' in js
    assert "/api/cover-letter" in js
    assert "Generate letter" in js


def test_cover_letter_route_registered():
    routes = ROUTES.read_text(encoding="utf-8")

    assert "post_cover_letter" in routes
    assert '"/api/cover-letter"' in routes


def test_cv_studio_defensibility_ui_wiring():
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = _dashboard_js()
    routes = ROUTES.read_text(encoding="utf-8")

    assert "studioDefensibilityBtn" in html
    assert "studioDefensibilityResult" in html
    assert "/api/cv-studio/defensibility" in js
    assert "analyzeStudioDefensibility" in js
    assert '"/api/cv-studio/defensibility"' in routes
