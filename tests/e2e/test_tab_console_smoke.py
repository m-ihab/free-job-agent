"""R3 split gate: click every tab; no uncaught page errors, no error-class console output.

The dashboard is classic shared-scope JS: an extraction mistake surfaces as a
ReferenceError/TypeError at init (bindEvents) or on first tab activation —
places markup-only assertions never look. This test is the automated form of
the DEEP-HANDOFF §3 manual click-through requirement and MUST stay green after
every static/*.js extraction.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus

try:
    from playwright.sync_api import Page

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    from typing import Any

    Page = Any  # type: ignore[assignment]
    PLAYWRIGHT_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="playwright is not installed")

# The failure classes a shared-scope split produces. Benign network noise
# (favicon 404s etc.) deliberately stays out of this gate.
ERROR_CLASS = re.compile(
    r"ReferenceError|SyntaxError|TypeError|is not defined|is not a function"
)


def test_every_tab_activates_without_js_errors(page: Page, live_server_url: str) -> None:
    page_errors: list[str] = []
    console_errors: list[str] = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )

    page.goto(live_server_url)

    tabs = page.locator("nav.tabs button[data-tab]")
    names = [tabs.nth(i).get_attribute("data-tab") for i in range(tabs.count())]
    assert "brain" in names, "Brain tab is missing from the dashboard rail"
    assert "skill-tree" in names, "Skill Tree tab is missing from the dashboard rail"
    assert names, "no tabs found — dashboard failed to render"

    for name in names:
        page.locator(f"button[data-tab='{name}']").click()
        page.locator(f"#tab-{name}").wait_for(state="visible")

    # Let the async tab loaders (api fetches) finish so their failures surface.
    page.wait_for_timeout(800)

    assert page_errors == [], f"uncaught page errors after tab sweep: {page_errors}"
    bad_console = [m for m in console_errors if ERROR_CLASS.search(m)]
    assert bad_console == [], f"error-class console output: {bad_console}"


def test_brain_tab_paints_seeded_graph_and_opens_job_details(
    page: Page,
    live_server_url: str,
    e2e_config: AppConfig,
    tmp_path: Path,
) -> None:
    page_errors: list[str] = []
    console_errors: list[str] = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    db = Database(e2e_config.db_path)  # type: ignore[arg-type]
    job = JobListing(
        title="Graph Data Scientist",
        company="Brainworks",
        description="Build Python graph models.",
        requirements=["Python", "Neo4j"],
        tech_stack=["Python", "Neo4j"],
        status=JobStatus.SCORED,
        fit_score=86,
    )
    db.save_job(job)
    db.replace_evidence_items(
        [{"kind": "project", "label": "Graph search", "value": "Python graph model", "source": "cv"}]
    )
    try:
        page.goto(live_server_url)
        page.locator("button[data-tab='brain']").click()
        page.locator("#brainCanvas").wait_for(state="visible")
        page.wait_for_function("() => window.JobAgentBrain?.state().nodeCount > 0")
        assert page.locator("#brainEmpty").is_hidden()
        assert "5 nodes" in (page.locator("#brainGraphStats").text_content() or "")
        page.evaluate("jobId => window.JobAgentBrain.selectNode(`job:${jobId}`)", job.id)
        page.locator("#brainDetails").get_by_text("Graph Data Scientist").wait_for()
        details = page.locator("#brainDetails").text_content() or ""
        assert "Fit score" in details
        assert "Search quality" in details
        page.locator("#brainMode3d").click()
        assert page.locator("#brainMode3d").get_attribute("aria-pressed") == "true"
        page.screenshot(path=str(tmp_path / "brain-seeded-3d.png"), full_page=True)
        assert page_errors == []
        assert console_errors == []
    finally:
        db.delete_job(job.id)
        db.replace_evidence_items([])


def test_skill_tree_renders_seeded_states_and_details(
    page: Page,
    live_server_url: str,
    e2e_config: AppConfig,
    tmp_path: Path,
) -> None:
    page_errors: list[str] = []
    console_errors: list[str] = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    db = Database(e2e_config.db_path)  # type: ignore[arg-type]
    job = JobListing(
        title="Data Scientist",
        company="Skillworks",
        description="Build Python services on AWS with DevOps ownership.",
        requirements=["Python", "AWS", "DevOps"],
        tech_stack=["Python", "AWS", "DevOps"],
        status=JobStatus.SCORED,
        fit_score=45,
    )
    db.save_job(job)
    try:
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(live_server_url)
        page.locator("button[data-tab='skill-tree']").click()
        page.locator("#skillTreeSvg").wait_for(state="visible")
        page.wait_for_function("() => document.querySelectorAll('#skillTreeSvg .skill-node').length > 0")
        assert page.locator(".skill-role-card").count() > 0
        assert page.locator("#skillTreeSvg .skill-node.locked").count() >= 1
        locked = page.locator("#skillTreeSvg .skill-node.locked").first
        locked.press("Enter")
        page.locator("#skillTreeDetails").get_by_text("How to unlock").wait_for()
        details = page.locator("#skillTreeDetails").text_content() or ""
        assert "low-score job(s) expose it as a gap" in details
        assert "Hypothetical re-score, not a promise" in details
        page.screenshot(path=str(tmp_path / "skill-tree-seeded-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 820, "height": 1000})
        columns = page.locator(".skill-tree-layout").evaluate(
            "node => getComputedStyle(node).gridTemplateColumns.split(' ').length"
        )
        assert columns == 1
        page.screenshot(path=str(tmp_path / "skill-tree-seeded-narrow.png"), full_page=True)
        assert page_errors == []
        assert console_errors == []
    finally:
        db.delete_job(job.id)


def test_insights_empty_states_replace_blank_charts(
    page: Page,
    live_server_url: str,
    tmp_path: Path,
) -> None:
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(live_server_url)
    page.locator("button[data-tab='insights']").click()
    page.locator("#tab-insights").wait_for(state="visible")

    for canvas_id in ("funnelChart", "sourcesChart", "scoreChart", "applicationsChart"):
        page.locator(f"#{canvas_id}Empty").wait_for(state="visible")
        assert page.locator(f"#{canvas_id}").is_hidden()
    page.screenshot(path=str(tmp_path / "insights-empty-desktop.png"), full_page=True)

    desktop_columns = page.locator(".insights-grid").evaluate(
        "node => getComputedStyle(node).gridTemplateColumns.split(' ').length"
    )
    assert desktop_columns == 2
    page.set_viewport_size({"width": 820, "height": 1000})
    mobile_columns = page.locator(".insights-grid").evaluate(
        "node => getComputedStyle(node).gridTemplateColumns.split(' ').length"
    )
    assert mobile_columns == 1
    page.screenshot(path=str(tmp_path / "insights-empty-narrow.png"), full_page=True)


def test_insights_charts_paint_seeded_metrics(
    page: Page,
    live_server_url: str,
    e2e_config: AppConfig,
    tmp_path: Path,
) -> None:
    db = Database(e2e_config.db_path)  # type: ignore[arg-type]
    jobs = [
        JobListing(title="Scored", company="A", source="manual", status=JobStatus.SCORED, fit_score=62),
        JobListing(title="Packet", company="B", source="manual", status=JobStatus.PACKET_READY, fit_score=76),
        JobListing(title="Applied", company="C", source="remoteok", status=JobStatus.APPLIED, fit_score=84),
        JobListing(title="Interview", company="D", source="remoteok", status=JobStatus.INTERVIEWING, fit_score=91),
    ]
    for job in jobs:
        db.save_job(job)
    try:
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(live_server_url)
        page.locator("button[data-tab='insights']").click()
        page.locator("#funnelChart").wait_for(state="visible")
        page.wait_for_function(
            "() => ['funnelChart','sourcesChart','scoreChart','applicationsChart']"
            ".every(id => Chart.getChart(document.getElementById(id)))"
        )
        tooltip_states = page.evaluate(
            "() => ['funnelChart','sourcesChart','scoreChart','applicationsChart']"
            ".map(id => Chart.getChart(document.getElementById(id)).options.plugins.tooltip.enabled)"
        )
        assert tooltip_states == [True, True, True, True]
        assert page.locator(".source-table-row").count() == 2
        page.locator("#themeToggleBtn").click()
        assert page.locator("html").get_attribute("data-theme") == "dark"
        page.screenshot(path=str(tmp_path / "insights-seeded-dark.png"), full_page=True)
    finally:
        for job in jobs:
            db.delete_job(job.id)
