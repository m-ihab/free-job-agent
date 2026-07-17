"""Source-contract tests for the standalone Filtered out dashboard module."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "job_agent" / "ui" / "static"
APP_JS = STATIC / "app.js"
FILTERS_JS = STATIC / "filters_view.js"
INDEX_HTML = STATIC / "index.html"
ESLINT = ROOT / "eslint.config.mjs"


def test_filtered_out_tab_and_deferred_module_are_registered_without_losing_anchors() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'data-tab="filtered-out"' in html
    assert 'id="tab-filtered-out"' in html
    assert '<script src="/static/filters_view.js" defer></script>' in html
    assert html.index('/static/career.js') < html.index('/static/filters_view.js')
    for existing_anchor in (
        'id="tab-jobs"',
        'id="tab-career"',
        'id="careerRefreshBtn"',
        '<script src="/static/career.js" defer></script>',
    ):
        assert existing_anchor in html


def test_filters_module_uses_r3_namespace_and_designed_states() -> None:
    source = FILTERS_JS.read_text(encoding="utf-8")

    assert "(function () {" in source
    assert "window.JobAgentFilters = { load }" in source
    assert 'api("/api/filtered-out")' in source
    assert "Loading filtered jobs" in source
    assert "Nothing filtered out" in source
    assert "Filtered jobs could not load" in source
    assert 'data-filtered-action="restore"' in source
    assert 'data-filtered-action="delete"' in source
    assert 'id="filteredOutRestoreAllBtn"' in source
    assert 'api("/api/filtered-out/action"' in source
    assert "window.confirm" in source
    assert 'document.body.addEventListener("click"' not in source


def test_app_dispatches_only_through_guarded_filters_namespace() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    assert (
        'if (name === "filtered-out" && window.JobAgentFilters) '
        "window.JobAgentFilters.load();"
    ) in source
    assert "loadFilteredOut" not in source
    assert '"src/job_agent/ui/static/filters_view.js"' in ESLINT.read_text(
        encoding="utf-8"
    )
