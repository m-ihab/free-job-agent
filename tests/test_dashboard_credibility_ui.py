"""Source contracts for the N3b dashboard credibility surfaces."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "job_agent" / "ui" / "static"
INDEX = STATIC / "index.html"
OVERVIEW = STATIC / "overview.js"
OVERVIEW_SHORTLIST = STATIC / "overview_shortlist.js"
TRACKER = STATIC / "tracker_view.js"
ACTIVITY = STATIC / "activity.js"
CAREER = STATIC / "career.js"
GRAPH = STATIC / "brain_graph.js"


def test_overview_shortlist_precedes_kpis_and_uses_real_action_and_dual_scores() -> None:
    html = INDEX.read_text(encoding="utf-8")
    script = OVERVIEW.read_text(encoding="utf-8") + OVERVIEW_SHORTLIST.read_text(encoding="utf-8")

    assert html.index('id="ovShortlist"') < html.index('id="ovHero"')
    assert "Your top 5 right now" in html
    assert 'api("/api/pipeline/today?limit=50")' in script
    assert "shortlistRank" in script
    assert "item.action" in script
    assert "search_quality_score" in script
    assert "No actionable jobs right now" in script
    assert 'data-job="${esc(item.job_id)}"' in script


def test_tracker_activity_surface_filters_and_copies_real_route_events() -> None:
    html = INDEX.read_text(encoding="utf-8")
    script = ACTIVITY.read_text(encoding="utf-8")

    for element_id in ("trackerActivity", "activityFilters", "activityCopyBtn"):
        assert f'id="{element_id}"' in html
    assert 'api(`/api/activity${query}`)' in script
    assert "data-subsystem" in script
    assert "navigator.clipboard.writeText" in script
    assert "item.message" in script
    assert "No recorded activity" in script


def test_career_identity_and_metric_navigation_are_keyboard_native() -> None:
    html = INDEX.read_text(encoding="utf-8")
    script = CAREER.read_text(encoding="utf-8")

    assert 'id="careerIdentity"' in html
    assert "Evidence" in script and "Claimed" in script
    assert "gaps.identity" in script
    assert '<button type="button" class="metric metric-link"' in script
    assert "data-goto" in script and "data-career-anchor" in script
    assert "scrollIntoView" in script


def test_brain_caption_states_the_renderer_actual_seeded_fallback() -> None:
    html = INDEX.read_text(encoding="utf-8")
    renderer = GRAPH.read_text(encoding="utf-8")

    assert 'id="brainTrustCaption"' in html
    assert "stable seeded positions" in html
    assert "No embedding coordinates are used" in html
    assert "node.meta.stable_seed" in renderer
    assert "golden" in renderer
