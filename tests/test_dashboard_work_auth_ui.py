"""Dashboard work-auth filter and badge wiring."""
from __future__ import annotations

from pathlib import Path


JOBS_JS = Path("src/job_agent/ui/static/jobs.js")
INDEX_HTML = Path("src/job_agent/ui/static/index.html")


def test_dashboard_has_work_auth_filter_controls():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="filterWorkAuth"' in html
    assert 'value="directly_applicable"' in html
    assert 'value="sponsorship_gated"' in html
    assert 'id="filterHideSponsorship"' in html


def test_dashboard_filters_and_renders_work_auth_badges():
    js = JOBS_JS.read_text(encoding="utf-8")

    assert "function workAuthBadge(" in js
    assert "function gratificationBadge(" in js
    assert 'job.work_auth_class !== "sponsorship_gated"' in js
    assert "filterWorkAuth" in js
    assert "filterHideSponsorship" in js
