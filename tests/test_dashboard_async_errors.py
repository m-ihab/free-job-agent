from __future__ import annotations

from pathlib import Path


STATIC_DIR = Path("src/job_agent/ui/static")


def _source() -> str:
    # The dashboard is app.js plus its extracted classic-script modules (R3
    # split) — the guarded wiring may live in any of them. A sorted glob puts
    # app.js first and studio.js before studio_tools.js, preserving the
    # anchor order the _between() extractions rely on.
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(STATIC_DIR.glob("*.js"))
    )


def _between(source: str, start: str, end: str) -> str:
    start_idx = source.index(start)
    end_idx = source.index(end, start_idx)
    return source[start_idx:end_idx]


def test_dashboard_async_actions_surface_cv_studio_errors() -> None:
    source = _source()

    reset = _between(source, "async function studioReset()", "async function studioPromote()")
    promote = _between(source, "async function studioPromote()", "async function studioToggleVersions()")
    reorder = _between(source, "async function studioApplyReorder()", "async function openStudioAsset")

    for body in (reset, promote, reorder):
        assert "catch (error)" in body
        assert "studioNotice" in body or "toast(" in body


def test_dashboard_batch_enrichment_surfaces_errors() -> None:
    source = _source()

    body = _between(source, "async function enrichBatch(jobIds)", "async function updateJobStatus")

    assert "catch (error)" in body
    assert "Batch enrichment failed" in body


def test_pull_fast_model_uses_single_progress_watcher() -> None:
    source = _source()
    body = _between(source, "async function pullFastModel()", "async function runAiAnalysis")

    assert "ollamaPullWatcher" in source
    assert "window.clearInterval(state.ollamaPullWatcher)" in body
    assert "state.ollamaPullWatcher = watcher" in body
    assert "state.ollamaPullWatcher = null" in body


def test_dashboard_does_not_swallow_empty_catches() -> None:
    assert "catch " + "{}" not in _source()
