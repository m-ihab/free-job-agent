"""Dashboard Tracker and Kanban render contract."""
from __future__ import annotations

from pathlib import Path


TRACKER_JS = Path("src/job_agent/ui/static/tracker_view.js")
KANBAN_JS = Path("src/job_agent/ui/static/kanban.js")


def test_tracker_render_dispatches_kanban_event():
    js = TRACKER_JS.read_text(encoding="utf-8")

    render_tracker = js.index("function renderTracker()")
    tracker_rendered_event = js.index("jobagent:tracker-rendered", render_tracker)

    assert tracker_rendered_event > render_tracker


def test_kanban_subscribes_to_tracker_render_event():
    js = KANBAN_JS.read_text(encoding="utf-8")

    assert "addEventListener('jobagent:tracker-rendered'" in js


def test_kanban_does_not_replace_tracker_renderer():
    js = KANBAN_JS.read_text(encoding="utf-8")

    assert "window.renderTracker =" not in js
