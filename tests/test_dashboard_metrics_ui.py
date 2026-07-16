from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "job_agent" / "ui" / "static"
INDEX = STATIC / "index.html"
INSIGHTS = STATIC / "insights.js"
OVERVIEW = STATIC / "overview.js"


def test_dashboard_loads_local_chartjs_and_metrics_surfaces() -> None:
    html = INDEX.read_text(encoding="utf-8")

    assert '<script src="/static/vendor/chart.umd.min.js" defer></script>' in html
    assert "chart.umd.min.js" in html
    assert "https://" not in html.split("chart.umd.min.js", 1)[0].rsplit("<script", 1)[-1]
    for element_id in (
        "funnelChart",
        "sourcesChart",
        "scoreChart",
        "applicationsChart",
        "sourceConversionTable",
        "statusSnapshot",
    ):
        assert f'id="{element_id}"' in html


def test_insights_uses_metrics_api_chart_types_tooltips_and_empty_states() -> None:
    script = INSIGHTS.read_text(encoding="utf-8")

    assert 'api("/api/metrics")' in script
    assert 'type: "bar"' in script
    assert 'type: "doughnut"' in script
    assert 'type: "line"' in script
    assert "tooltip" in script
    assert "chart-empty" in script
    assert "applications_over_time" in script
    assert "score_distribution" in script
    assert "conversion_rate" in script


def test_overview_kpis_come_from_metrics_endpoint() -> None:
    script = OVERVIEW.read_text(encoding="utf-8")

    assert 'window.api("/api/metrics")' in script
    assert "metrics.kpis" in script


def test_pwa_manifest_and_app_mode_launcher_are_local_only() -> None:
    html = INDEX.read_text(encoding="utf-8")
    manifest_path = STATIC / "manifest.webmanifest"
    launcher_path = ROOT / "scripts" / "launch_app.ps1"

    assert '<link rel="manifest" href="/manifest.webmanifest"' in html
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"
    assert not any("http://" in str(value) or "https://" in str(value) for value in manifest.values())
    launcher = launcher_path.read_text(encoding="utf-8")
    assert "127.0.0.1:8765" in launcher
    assert "--app=" in launcher
    assert "Start-Process" in launcher
