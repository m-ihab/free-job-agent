"""Source-contract tests for the standalone Career dashboard module."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "job_agent" / "ui" / "static"
APP_JS = STATIC / "app.js"
CAREER_JS = STATIC / "career.js"
INDEX_HTML = STATIC / "index.html"
ESLINT = ROOT / "eslint.config.mjs"


def test_career_tab_and_deferred_module_are_registered() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'data-tab="career"' in html
    assert 'id="tab-career"' in html
    assert '<script src="/static/career.js" defer></script>' in html
    assert html.index('/static/outreach.js') < html.index('/static/career.js')


def test_career_module_uses_r3_namespace_and_all_read_routes() -> None:
    source = CAREER_JS.read_text(encoding="utf-8")

    assert "(function () {" in source
    assert "window.JobAgentCareer = { load }" in source
    assert 'api(`/api/career/gap-report?threshold=${threshold}`)' in source
    assert 'api("/api/career/cert-plan")' in source
    assert 'api("/api/career/project-plan")' in source
    assert "simulated" in source
    assert "Loading Career Engine" in source
    assert "No scored jobs yet" in source
    assert "Career Engine could not load" in source
    assert 'document.body.addEventListener("click"' not in source


def test_app_dispatches_only_through_guarded_career_namespace() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    assert (
        'if (name === "career" && window.JobAgentCareer) '
        "window.JobAgentCareer.load();"
    ) in source
    assert "loadCareer" not in source
    assert '"src/job_agent/ui/static/career.js"' in ESLINT.read_text(encoding="utf-8")
