from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "job_agent" / "ui" / "static"
INDEX = STATIC / "index.html"
BRAIN = STATIC / "brain.js"
GRAPH_RENDERER = STATIC / "brain_graph.js"
GRAPH_LAYOUT = STATIC / "brain_graph_layout.js"
GESTURES = STATIC / "graph_gestures.js"


def test_dashboard_has_brain_tab_canvas_controls_legend_and_details() -> None:
    html = INDEX.read_text(encoding="utf-8")

    assert 'data-tab="brain"' in html
    assert 'id="tab-brain"' in html
    for element_id in (
        "brainCanvas", "brainEmpty", "brainDetails", "brainMode2d", "brainMode3d",
        "brainYaw", "brainPitch", "brainZoom", "brainLegend",
    ):
        assert f'id="{element_id}"' in html
    assert '<script src="/static/brain.js" defer></script>' in html


def test_brain_uses_local_canvas_force_projection_and_lifecycle_guards() -> None:
    script = BRAIN.read_text(encoding="utf-8") + GRAPH_RENDERER.read_text(encoding="utf-8") + GRAPH_LAYOUT.read_text(encoding="utf-8")

    assert 'api("/api/graph")' in script
    assert 'getContext("2d")' in script
    assert "requestAnimationFrame" in script
    assert "visibilitychange" in script
    assert "prefers-reduced-motion: reduce" in script
    assert "Math.sin" in script and "Math.cos" in script
    assert "yaw" in script and "pitch" in script and "zoom" in script
    assert "repulsion" in script and "spring" in script and "centering" in script
    assert "WebGLRenderingContext" not in script
    assert "three.js" not in script.casefold()
    assert "http://" not in script and "https://" not in script
    assert "stable_seed_no_relations" in script
    assert "Evidence entries" in script and "Profile/CV claims" in script


def test_brain_binds_pointer_touch_wheel_reset_and_keyboard_interactions() -> None:
    html = INDEX.read_text(encoding="utf-8")
    script = GRAPH_RENDERER.read_text(encoding="utf-8") + GESTURES.read_text(encoding="utf-8")

    assert '<script src="/static/graph_gestures.js" defer></script>' in html
    assert "drag \u00b7 scroll to zoom" in html
    for event_name in ("pointerdown", "pointermove", "pointerup", "wheel", "dblclick", "keydown"):
        assert f'addEventListener("{event_name}"' in script
    assert "onPinch" in script and "onTap" in script
    assert "prefers-reduced-motion: reduce" in script
    assert "orbitVelocity" in script and "resetView" in script


def test_brain_defaults_to_persisted_3d_mode_with_accurate_discoverability_copy() -> None:
    html = INDEX.read_text(encoding="utf-8")
    script = BRAIN.read_text(encoding="utf-8") + GRAPH_RENDERER.read_text(encoding="utf-8")

    assert 'id="brainMode2d" aria-pressed="false"' in html
    assert 'id="brainMode3d" aria-pressed="true"' in html
    assert 'id="brainGestureHint"' in html and "drag to orbit \u00b7 scroll to zoom" in html
    assert 'let mode = "3d"' in script
    assert 'localStorage.getItem("job-agent-brain-mode")' in script
    assert 'localStorage.setItem("job-agent-brain-mode", mode)' in script
    assert 'mode === "3d" ? "drag to orbit \u00b7 scroll to zoom"' in script
    assert '"drag to pan \u00b7 drag a node to pin"' in script


def test_brain_2d_node_drag_pins_unpins_and_keeps_tap_selection() -> None:
    script = GRAPH_RENDERER.read_text(encoding="utf-8") + GRAPH_LAYOUT.read_text(encoding="utf-8")

    assert "draggedNode" in script
    assert "Math.max(node.sr, 12)" in script
    assert "node.pinned" in script
    assert "if (node.pinned)" in script
    assert "onTap(point)" in script and "options.onSelect?.(node.id)" in script
    assert "onDoubleActivate(point)" in script
    assert "node.pinned = false" in script


def test_brain_declutters_nodes_and_uses_zoom_label_lod_with_selected_priority() -> None:
    script = GRAPH_RENDERER.read_text(encoding="utf-8") + GRAPH_LAYOUT.read_text(encoding="utf-8")

    assert "const minDistance = radiusFor(a) + radiusFor(b) + 6" in script
    assert "labelRects" in script and "measureText" in script
    assert "rectsIntersect" in script
    assert "node.id === selected" in script
    assert "labelDegreeThreshold" in script and "zoom" in script
