"""Tests for the HiringCafe kill-gate watcher (baseline/diff semantics)."""
from __future__ import annotations

import json

import job_agent.killgate_watch as kg


class _Resp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


def _patch_pages(monkeypatch, pages: dict[str, str]):
    import job_agent.utils.net as net

    monkeypatch.setattr(net, "safe_get", lambda url, headers=None, timeout=None: _Resp(pages[url]))


SOURCES = (
    kg.WatchSource("https://hiring.cafe", "primary"),
    kg.WatchSource("https://reddit.example/search.json", "chatter"),
)


def test_scan_hits_finds_keywords_case_insensitively():
    assert kg.scan_hits("Try our new Saved Search and get NOTIFIED!") == ("get notified", "saved search")
    assert kg.scan_hits("just a jobs board") == ()


def test_check_source_handles_errors(monkeypatch):
    import job_agent.utils.net as net

    def _boom(*a, **k):
        raise RuntimeError("dns fail")

    monkeypatch.setattr(net, "safe_get", _boom)
    check = kg.check_source(kg.WatchSource("https://hiring.cafe", "primary"))
    assert not check.ok
    assert "RuntimeError" in check.error


def test_first_run_establishes_baseline_without_tripping(monkeypatch, tmp_path):
    _patch_pages(monkeypatch, {
        "https://hiring.cafe": "welcome — set a job alert today",
        "https://reddit.example/search.json": "{}",
    })
    state = tmp_path / "state.json"
    report = kg.run_watch(SOURCES, state_file=state)
    assert report.baseline_established
    assert not report.tripped
    assert report.new_hits["https://hiring.cafe"] == ("job alert",)
    saved = json.loads(state.read_text())
    assert saved["hits"]["https://hiring.cafe"] == ["job alert"]


def test_no_trip_when_nothing_new(monkeypatch, tmp_path):
    pages = {
        "https://hiring.cafe": "set a job alert today",
        "https://reddit.example/search.json": "{}",
    }
    _patch_pages(monkeypatch, pages)
    state = tmp_path / "state.json"
    kg.run_watch(SOURCES, state_file=state)  # baseline
    report = kg.run_watch(SOURCES, state_file=state)  # same content
    assert not report.tripped
    assert report.new_hits == {}


def test_trips_on_new_primary_hit(monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    _patch_pages(monkeypatch, {
        "https://hiring.cafe": "just a jobs board",
        "https://reddit.example/search.json": "{}",
    })
    kg.run_watch(SOURCES, state_file=state)  # clean baseline
    _patch_pages(monkeypatch, {
        "https://hiring.cafe": "NEW: create a saved search and get email alerts",
        "https://reddit.example/search.json": "{}",
    })
    report = kg.run_watch(SOURCES, state_file=state)
    assert report.tripped
    assert "saved search" in report.new_hits["https://hiring.cafe"]


def test_chatter_hits_only_flag_investigate(monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    _patch_pages(monkeypatch, {
        "https://hiring.cafe": "just a jobs board",
        "https://reddit.example/search.json": "nothing here",
    })
    kg.run_watch(SOURCES, state_file=state)
    _patch_pages(monkeypatch, {
        "https://hiring.cafe": "just a jobs board",
        "https://reddit.example/search.json": "hiring cafe finally added saved search?!",
    })
    report = kg.run_watch(SOURCES, state_file=state)
    assert not report.tripped
    assert report.investigate == ("https://reddit.example/search.json",)


def test_failed_source_does_not_wipe_baseline_or_trip(monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    _patch_pages(monkeypatch, {
        "https://hiring.cafe": "set a job alert",
        "https://reddit.example/search.json": "{}",
    })
    kg.run_watch(SOURCES, state_file=state)

    import job_agent.utils.net as net

    def _boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(net, "safe_get", _boom)
    report = kg.run_watch(SOURCES, state_file=state)
    assert not report.tripped
    assert all(not check.ok for check in report.checks)


def test_main_exit_codes(monkeypatch):
    monkeypatch.setattr(kg, "run_watch", lambda *a, **k: kg.WatchReport(tripped=True))
    assert kg.main() == 2
    monkeypatch.setattr(kg, "run_watch", lambda *a, **k: kg.WatchReport(tripped=False))
    assert kg.main() == 0
