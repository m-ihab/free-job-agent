"""Source contract for consistent dashboard connection-loss recovery."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "job_agent" / "ui" / "static"
MESSAGE = "Dashboard server not reachable — restart it (launch.ps1) and refresh"


def test_connection_lost_banner_is_shared_and_used_by_dashboard_loaders() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function renderConnectionLost" in app
    assert MESSAGE in app
    assert "Retry" in app

    expected = {
        "overview.js": "renderConnectionLost",
        "insights.js": "renderConnectionLost",
        "pipeline.js": "renderConnectionLost",
        "brain.js": "renderConnectionLost",
        "skill_tree.js": "renderConnectionLost",
        "filters_view.js": "renderConnectionLost",
    }
    for filename, helper in expected.items():
        source = (STATIC / filename).read_text(encoding="utf-8")
        assert helper in source, f"{filename} does not use the shared connection-loss banner"
        assert "TypeError" in source, f"{filename} does not distinguish a rejected fetch"
