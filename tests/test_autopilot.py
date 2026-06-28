"""Behavioural tests for the autonomous hunting loop.

All search / pipeline / auto-apply collaborators are mocked. We assert the
cycle advances, respects limits, never halts on NEEDS_MANUAL, and shapes its
summary correctly.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import job_agent.autopilot as ap
from job_agent.autopilot import Autopilot, AutopilotConfig, _is_expected_noise


# ── _is_expected_noise (dead-board filter) ───────────────────────────────────


@pytest.mark.parametrize("message, expected", [
    ("greenhouse/Acme: HTTP 404", True),
    ("lever/Foo: board not found", True),
    ("source: 410 gone", True),
    ("francetravail/data: timeout after 30s", False),
    ("", False),
])
def test_is_expected_noise(message, expected):
    assert _is_expected_noise(message) is expected


# ── Config ────────────────────────────────────────────────────────────────────


def test_autopilot_config_defaults_are_internship_focused():
    cfg = AutopilotConfig()
    assert cfg.contract_type == "stage_and_alternance"
    assert cfg.auto_apply is False
    assert cfg.auto_apply_mode == "fill_and_confirm"
    assert cfg.max_packets_per_cycle == 5


# ── Fake DB used by _run_cycle ────────────────────────────────────────────────


class _FakeDB:
    def __init__(self):
        self.statuses = {}
        self.events = []

    def initialize(self):
        return None

    def is_source_broken(self, kind, slug):
        return True  # skip every CAC40 slug to keep the cycle fast

    def list_jobs_without_packets(self, limit=10):
        return []

    def list_ai_cache_for_job(self, job_id):
        return {}

    def list_broken_sources(self):
        return []

    def list_jobs(self, *a, **k):
        return []


def _config(tmp_path: Path):
    return SimpleNamespace(db_path=tmp_path / "jobs.db")


def _autopilot(tmp_path, monkeypatch, opts=None):
    pilot = Autopilot(_config(tmp_path), opts or AutopilotConfig(
        queries=["data scientist"],
        use_france_travail=False,
        use_multi_source=False,
        use_cac40_sweep=False,
    ))
    monkeypatch.setattr(ap, "Database", lambda path: _FakeDB())
    monkeypatch.setattr(ap, "ApplicationTracker", lambda db: SimpleNamespace())
    monkeypatch.setattr(pilot, "_planned_queries", lambda: ["data scientist"])
    monkeypatch.setattr(ap, "load_profile_bundle", lambda config: (object(), object(), object()))
    return pilot


# ── _run_cycle ────────────────────────────────────────────────────────────────


def test_run_cycle_adds_new_jobs_and_builds_packet(tmp_path, monkeypatch):
    opts = AutopilotConfig(queries=["data scientist"], use_france_travail=False,
                           use_cac40_sweep=False, auto_packet_threshold=70)
    pilot = _autopilot(tmp_path, monkeypatch, opts)

    job = SimpleNamespace(id="job-1")
    monkeypatch.setattr(ap, "search_all_free_sources",
                        lambda **k: {"jobs": [job], "errors": {}})
    monkeypatch.setattr(ap, "add_job_to_tracker",
                        lambda config, j: (SimpleNamespace(id="job-1"), True))
    packet = SimpleNamespace(id="pkt-1", fit_score=85)
    monkeypatch.setattr(ap, "generate_packet_for_job", lambda *a, **k: packet)

    summary = pilot._run_cycle()

    assert summary["jobs_added"] == 1
    assert summary["packets_built"] == 1
    assert pilot.state.jobs_added_total == 1


def test_run_cycle_skips_weak_ai_jobs(tmp_path, monkeypatch):
    opts = AutopilotConfig(queries=["data scientist"], use_france_travail=False, use_cac40_sweep=False)
    pilot = _autopilot(tmp_path, monkeypatch, opts)

    class _WeakDB(_FakeDB):
        def list_ai_cache_for_job(self, job_id):
            return {"fit": {"verdict": "weak"}}

    monkeypatch.setattr(ap, "Database", lambda path: _WeakDB())
    monkeypatch.setattr(ap, "search_all_free_sources",
                        lambda **k: {"jobs": [SimpleNamespace(id="job-1")], "errors": {}})
    monkeypatch.setattr(ap, "add_job_to_tracker",
                        lambda config, j: (SimpleNamespace(id="job-1"), True))
    built = []
    monkeypatch.setattr(ap, "generate_packet_for_job",
                        lambda *a, **k: built.append(1) or SimpleNamespace(id="x", fit_score=90))

    summary = pilot._run_cycle()

    assert summary["ai_skipped"] == 1
    assert summary["packets_built"] == 0
    assert not built  # weak job never reaches packet generation


def test_run_cycle_respects_max_packets_per_cycle(tmp_path, monkeypatch):
    opts = AutopilotConfig(queries=["data scientist"], use_france_travail=False,
                           use_cac40_sweep=False, max_packets_per_cycle=2, auto_packet_threshold=0)
    pilot = _autopilot(tmp_path, monkeypatch, opts)

    jobs = [SimpleNamespace(id=f"job-{i}") for i in range(5)]
    monkeypatch.setattr(ap, "search_all_free_sources", lambda **k: {"jobs": jobs, "errors": {}})
    counter = {"n": 0}

    def _add(config, j):
        counter["n"] += 1
        return SimpleNamespace(id=j.id), True

    monkeypatch.setattr(ap, "add_job_to_tracker", _add)
    built_ids = []

    def _build(config, job_id, **k):
        built_ids.append(job_id)
        return SimpleNamespace(id=f"pkt-{job_id}", fit_score=90)

    monkeypatch.setattr(ap, "generate_packet_for_job", _build)

    summary = pilot._run_cycle()

    assert summary["jobs_added"] == 5  # all 5 ingested
    assert len(built_ids) == 2  # but only 2 packets built this cycle


def test_run_cycle_continues_after_packet_error(tmp_path, monkeypatch):
    opts = AutopilotConfig(queries=["data scientist"], use_france_travail=False,
                           use_cac40_sweep=False, auto_packet_threshold=0)
    pilot = _autopilot(tmp_path, monkeypatch, opts)

    monkeypatch.setattr(ap, "search_all_free_sources",
                        lambda **k: {"jobs": [SimpleNamespace(id="job-1")], "errors": {}})
    monkeypatch.setattr(ap, "add_job_to_tracker",
                        lambda config, j: (SimpleNamespace(id="job-1"), True))

    def _boom(*a, **k):
        raise RuntimeError("packet build crashed")

    monkeypatch.setattr(ap, "generate_packet_for_job", _boom)

    summary = pilot._run_cycle()  # must not raise — cycle is resilient

    assert summary["jobs_added"] == 1
    assert summary["packets_built"] == 0


def test_run_cycle_filters_dead_board_noise_from_errors(tmp_path, monkeypatch):
    opts = AutopilotConfig(queries=["data scientist"], use_france_travail=False,
                           use_cac40_sweep=False)
    pilot = _autopilot(tmp_path, monkeypatch, opts)

    monkeypatch.setattr(ap, "search_all_free_sources",
                        lambda **k: {"jobs": [], "errors": {"deadboard": "404 not found",
                                                            "realsrc": "timeout"}})
    monkeypatch.setattr(ap, "add_job_to_tracker",
                        lambda config, j: (SimpleNamespace(id=j.id), True))
    monkeypatch.setattr(ap, "generate_packet_for_job", lambda *a, **k: None)

    summary = pilot._run_cycle()

    joined = " ".join(summary["errors"])
    assert "404" not in joined  # dead board filtered
    assert "timeout" in joined  # real error surfaced


# ── _planned_queries ──────────────────────────────────────────────────────────


def test_planned_queries_dedupe_and_cap(tmp_path, monkeypatch, caplog):
    pilot = Autopilot(_config(tmp_path), AutopilotConfig(queries=["data scientist"]))
    monkeypatch.setattr(ap, "expand_role_family", lambda seed: [seed, "data engineer"])
    monkeypatch.setattr(ap, "expand_france_search_queries",
                        lambda seed, limit, language: ["stage data", "data scientist"])
    # AI plan unreachable -> deterministic fallback still works, with a log breadcrumb.
    monkeypatch.setattr(ap, "load_profile_bundle", lambda config: (_ for _ in ()).throw(RuntimeError()))
    caplog.set_level(logging.WARNING, logger="job_agent.autopilot_queries")

    planned = pilot._planned_queries()

    assert "data scientist" in planned
    assert "data engineer" in planned
    assert len(planned) == len(set(p.casefold() for p in planned))  # no dupes
    assert len(planned) <= 24
    assert "Autopilot AI query planning failed" in caplog.text


def test_planned_queries_includes_ai_suggestions(tmp_path, monkeypatch):
    pilot = Autopilot(_config(tmp_path), AutopilotConfig(queries=["data scientist"]))
    monkeypatch.setattr(ap, "expand_role_family", lambda seed: [seed])
    monkeypatch.setattr(ap, "expand_france_search_queries", lambda seed, limit, language: [])
    monkeypatch.setattr(ap, "load_profile_bundle", lambda config: (object(), object(), object()))
    monkeypatch.setattr(ap, "suggest_search_queries",
                        lambda *a, **k: {"queries": ["machine learning stage"]})

    planned = pilot._planned_queries()

    assert "machine learning stage" in planned


# ── Lifecycle (no real thread work needed for status) ────────────────────────


def test_status_reports_not_running_initially(tmp_path):
    pilot = Autopilot(_config(tmp_path), AutopilotConfig(queries=["x"]))
    status = pilot.status()
    assert status["running"] is False
    assert status["cycles_completed"] == 0
    assert status["config"]["queries"] == ["x"]


def test_stop_is_idempotent_when_not_running(tmp_path):
    pilot = Autopilot(_config(tmp_path), AutopilotConfig(queries=["x"]))
    state = pilot.stop()
    assert state.running is False
