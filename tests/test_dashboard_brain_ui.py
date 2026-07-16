from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "job_agent" / "ui" / "static"
INDEX = STATIC / "index.html"
BRAIN = STATIC / "brain.js"
GRAPH_RENDERER = STATIC / "brain_graph.js"


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
    script = BRAIN.read_text(encoding="utf-8") + GRAPH_RENDERER.read_text(encoding="utf-8")

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
