"""E2E tests for the free-job-agent web dashboard.

Drives Chromium via playwright against an isolated test server started in a
background thread.  The server uses a temp directory so these tests never
touch the user's real profile or database.

Fixtures (e2e_config, live_server_url) are defined in conftest.py.

Run with:
    pytest tests/e2e/ --browser chromium -q
"""
from __future__ import annotations

import json

import pytest

try:
    from playwright.sync_api import Page, expect
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    from typing import Any

    Page = Any  # type: ignore[assignment]
    expect = None  # type: ignore[assignment]
    PLAYWRIGHT_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="playwright is not installed")


def _post_json(page: Page, live_server_url: str, path: str, payload: dict):
    """POST through the dashboard's CSRF guard.

    APIRequestContext bypasses the page's fetch wrapper, so we navigate first to
    read the injected per-process token and replay it as a same-origin request.
    """
    page.goto(live_server_url)
    token = page.get_attribute('meta[name="csrf-token"]', "content") or ""
    return page.request.post(
        f"{live_server_url}{path}",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Origin": live_server_url,
            "X-Job-Agent-Token": token,
        },
    )


# ---------------------------------------------------------------------------
# Page load
# ---------------------------------------------------------------------------


def test_page_title(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    expect(page).to_have_title("Paris Data Career Copilot")


def test_page_header_visible(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    expect(page.locator("h1")).to_contain_text("Copilot")


def test_all_nav_tabs_present(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    nav = page.locator("nav.tabs")
    expect(nav).to_be_visible()
    for name in ("Search", "Jobs", "Autopilot", "CV Studio", "Portfolio", "Add Job"):
        expect(nav.get_by_role("button", name=name)).to_be_visible()


# ---------------------------------------------------------------------------
# Tab navigation
# ---------------------------------------------------------------------------


def test_jobs_tab_activates_on_click(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    page.locator("button[data-tab='jobs']").click()
    expect(page.locator("#tab-jobs")).to_be_visible()


def test_studio_tab_shows_compile_button(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    page.locator("button[data-tab='studio']").click()
    expect(page.locator("#studioCompileBtn")).to_be_visible()


def test_studio_tab_has_preview_iframe(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    page.locator("button[data-tab='studio']").click()
    expect(page.locator("#studioPreview")).to_be_attached()


def test_add_job_tab_shows_textarea(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    page.locator("button[data-tab='add']").click()
    expect(page.locator("#jobTextInput")).to_be_visible()


def test_profile_tab_is_visible(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    page.locator("button[data-tab='profile']").click()
    expect(page.locator("#tab-profile")).to_be_visible()


# ---------------------------------------------------------------------------
# API: state / jobs / stats
# ---------------------------------------------------------------------------


def test_api_state_returns_profile_block(page: Page, live_server_url: str) -> None:
    resp = page.request.get(f"{live_server_url}/api/state")
    assert resp.ok, f"Expected 200, got {resp.status}"
    data = resp.json()
    assert "profile" in data
    assert "latex_ready" in data["profile"]
    assert "sources" in data


def test_api_jobs_initially_empty(page: Page, live_server_url: str) -> None:
    resp = page.request.get(f"{live_server_url}/api/jobs")
    assert resp.ok
    data = resp.json()
    assert isinstance(data.get("jobs"), list)


def test_api_stats_returns_total_key(page: Page, live_server_url: str) -> None:
    resp = page.request.get(f"{live_server_url}/api/stats")
    assert resp.ok
    assert "total" in resp.json()


def test_api_search_links_returns_groups(page: Page, live_server_url: str) -> None:
    resp = _post_json(
        page, live_server_url, "/api/search-links",
        {"query": "data scientist", "location": "Paris"},
    )
    assert resp.ok
    data = resp.json()
    assert isinstance(data.get("groups"), list)
    assert data.get("query_count", 0) >= 1


def test_api_studio_compile_bad_input_returns_structured_error(
    page: Page, live_server_url: str
) -> None:
    """Compile with JSON (not LaTeX) must return {'ok': False}, not a 500."""
    resp = _post_json(
        page, live_server_url, "/api/cv-studio/compile",
        {"text": '{"contact": {}}'},
    )
    data = resp.json()
    assert "ok" in data
    assert data["ok"] is False
    assert "reason" in data


# ---------------------------------------------------------------------------
# Search tab controls
# ---------------------------------------------------------------------------


def test_search_query_input_has_default(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    expect(page.locator("#queryInput")).to_have_value("data scientist")


def test_search_location_input_visible(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    expect(page.locator("#locationInput")).to_be_visible()


def test_search_language_select_visible(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    expect(page.locator("#languageSelect")).to_be_visible()


# ---------------------------------------------------------------------------
# Modal CSS regression — "new buttons do nothing" bug
#
# Root cause: .modal-overlay had no CSS → modals were inline elements with
# zero visibility.  After the fix, .modal-overlay must be position:fixed.
# ---------------------------------------------------------------------------


def test_modal_overlay_is_fixed_position(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    page.evaluate("""
        const el = Object.assign(document.createElement('div'), {
            className: 'modal-overlay', id: '_testOverlay'
        });
        el.innerHTML = '<div class="modal-box"><p>Test</p></div>';
        document.body.appendChild(el);
    """)
    position = page.evaluate(
        "getComputedStyle(document.getElementById('_testOverlay')).position"
    )
    assert position == "fixed", f"Expected position:fixed, got '{position}'"


def test_modal_overlay_covers_viewport(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    page.evaluate("""
        const el = Object.assign(document.createElement('div'), {
            className: 'modal-overlay', id: '_testOverlay2'
        });
        el.innerHTML = '<div class="modal-box" id="_testBox">Content</div>';
        document.body.appendChild(el);
    """)
    style = page.evaluate("""
        const s = getComputedStyle(document.getElementById('_testOverlay2'));
        ({ inset: s.inset, zIndex: s.zIndex })
    """)
    z = int(style.get("zIndex") or "0")
    assert z > 100, f"Expected high z-index for overlay, got {z}"


def test_modal_box_has_nonzero_width(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    page.evaluate("""
        const el = Object.assign(document.createElement('div'), {
            className: 'modal-overlay', id: '_testOverlay3'
        });
        el.innerHTML = '<div class="modal-box" id="_testBox3">Content</div>';
        document.body.appendChild(el);
    """)
    width = page.evaluate(
        "document.getElementById('_testBox3').getBoundingClientRect().width"
    )
    assert width > 100, f"modal-box should be at least 100px wide, got {width}"


# ---------------------------------------------------------------------------
# Interview prep panel regression
#
# Before the fix, generateInterviewPrep() opened a modal that was invisible
# due to missing CSS.  After the fix it populates #prepPanel in the sidebar.
# ---------------------------------------------------------------------------


def test_prep_panel_exists_in_dom(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    expect(page.locator("#prepPanel")).to_be_attached()


def test_prep_panel_hidden_by_default(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    classes = page.locator("#prepPanel").get_attribute("class") or ""
    assert "hidden" in classes, "prep panel should start hidden"


def test_prep_panel_has_title_and_body(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    expect(page.locator("#prepPanelTitle")).to_be_attached()
    expect(page.locator("#prepPanelBody")).to_be_attached()


def test_prep_panel_close_button_present(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    expect(page.locator("#prepPanelCloseBtn")).to_be_attached()


# ---------------------------------------------------------------------------
# Contract-type terms in page — filter UI
# ---------------------------------------------------------------------------


def test_jobs_tab_has_contract_filter(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    page.locator("button[data-tab='jobs']").click()
    expect(page.locator("#filterContract")).to_be_visible()


# ---------------------------------------------------------------------------
# Autopilot tab
# ---------------------------------------------------------------------------


def test_autopilot_tab_renders(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    page.locator("button[data-tab='autopilot']").click()
    expect(page.locator("#tab-autopilot")).to_be_visible()


def test_auto_apply_preview_button_present(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    page.locator("button[data-tab='autopilot']").click()
    expect(page.locator("#autoApplyPreviewBtn")).to_be_visible()


# ---------------------------------------------------------------------------
# Theme toggle
# ---------------------------------------------------------------------------


def test_theme_toggle_button_present(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    expect(page.locator("#themeToggleBtn")).to_be_visible()


def test_theme_toggle_changes_data_theme(page: Page, live_server_url: str) -> None:
    page.goto(live_server_url)
    before = page.locator("html").get_attribute("data-theme") or "light"
    page.locator("#themeToggleBtn").click()
    after = page.locator("html").get_attribute("data-theme") or "light"
    assert before != after, "theme toggle should flip data-theme on <html>"


# ---------------------------------------------------------------------------
# Static assets served correctly
# ---------------------------------------------------------------------------


def test_css_served_with_correct_content_type(page: Page, live_server_url: str) -> None:
    resp = page.request.get(f"{live_server_url}/static/app.css")
    assert resp.ok
    ct = resp.headers.get("content-type", "")
    assert "css" in ct, f"Expected CSS content-type, got '{ct}'"


def test_js_served_with_correct_content_type(page: Page, live_server_url: str) -> None:
    resp = page.request.get(f"{live_server_url}/static/app.js")
    assert resp.ok
    ct = resp.headers.get("content-type", "")
    assert "javascript" in ct or "js" in ct, f"Expected JS content-type, got '{ct}'"
