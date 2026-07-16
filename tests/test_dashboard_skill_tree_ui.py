from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "job_agent" / "ui" / "static"
INDEX = STATIC / "index.html"
SCRIPT = STATIC / "skill_tree.js"
CAREER = STATIC / "career.js"
GESTURES = STATIC / "graph_gestures.js"


def test_dashboard_has_skill_tree_tab_dag_panel_and_role_readiness() -> None:
    html = INDEX.read_text(encoding="utf-8")

    assert 'data-tab="skill-tree"' in html
    assert 'id="tab-skill-tree"' in html
    for element_id in (
        "skillTreeRoles",
        "skillTreeSvg",
        "skillTreeEmpty",
        "skillTreeDetails",
        "skillTreeLegend",
    ):
        assert f'id="{element_id}"' in html
    assert '<script src="/static/skill_tree.js" defer></script>' in html


def test_skill_tree_uses_local_svg_engine_data_and_accessible_nodes() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'api("/api/skill-tree")' in script
    assert "createElementNS" in script
    assert 'setAttribute("tabindex", "0")' in script
    assert 'setAttribute("role", "button")' in script
    assert "evidenceCount" in script and "jobsBlocked" in script
    assert "scoreLift" in script and "readiness" in script
    assert "http://" not in script and "https://" not in script


def test_career_stat_tiles_link_to_skill_tree() -> None:
    script = CAREER.read_text(encoding="utf-8")

    assert 'data-skill-tree-link' in script
    assert 'activateTab("skill-tree")' in script


def test_skill_tree_binds_viewbox_pan_zoom_pinch_and_reset() -> None:
    html = INDEX.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8") + GESTURES.read_text(encoding="utf-8")

    assert 'id="skillTreeSvg" role="img"' in html
    assert "drag \u00b7 scroll to zoom" in html
    assert "viewBox" in script and "bindSurface" in script
    for event_name in ("pointerdown", "pointermove", "pointerup", "wheel", "dblclick"):
        assert f'addEventListener("{event_name}"' in script
    assert "onPinch" in script and "resetView" in script
    assert "DRAG_THRESHOLD" in script
