"""Round-2 behavioural tests for ``job_agent.ui.route_helpers`` free functions.

Targets the remaining uncovered branches: ``_file_response_path`` (bad path /
no roots), ``_resolve_github_handle`` (profile read + sanitization), ``_save_jobs``
(packet-prepare failure path), ``_api_search`` / ``_one_click_hunt`` aggregation
with the network sources mocked, and ``_export_internships``. No real network /
LLM / LaTeX is invoked.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_agent.config import AppConfig
from job_agent.schemas.job import JobListing
from job_agent.ui import route_helpers as rh


@pytest.fixture
def config(tmp_path) -> AppConfig:
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    profiles_dir = tmp_path / "profiles"
    for d in (data_dir, outputs_dir, profiles_dir):
        d.mkdir(parents=True, exist_ok=True)
    return AppConfig(data_dir=data_dir, outputs_dir=outputs_dir, profiles_dir=profiles_dir)


def _job(title="Data Scientist", company="ACME") -> JobListing:
    return JobListing(title=title, company=company, source="paste", raw_text="x")


# --- _safe_int -----------------------------------------------------------


def test_safe_int_clamps_to_maximum():
    assert rh._safe_int(9999, default=5, minimum=1, maximum=50) == 50


def test_safe_int_falls_back_on_non_numeric():
    assert rh._safe_int("abc", default=7, minimum=1, maximum=100) == 7


# --- _file_response_path -------------------------------------------------


def test_file_response_path_returns_file_inside_root(config):
    target = config.outputs_dir / "a.txt"
    target.write_text("x", encoding="utf-8")
    assert rh._file_response_path(config, str(target)) == target.resolve()


def test_file_response_path_rejects_path_outside_roots(config, tmp_path):
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x", encoding="utf-8")
    assert rh._file_response_path(config, str(outside)) is None


def test_file_response_path_returns_none_for_directory(config):
    # An existing path inside a root but not a file -> None.
    assert rh._file_response_path(config, str(config.outputs_dir)) is None


# --- _resolve_github_handle ----------------------------------------------


def test_resolve_github_handle_prefers_explicit_payload(config):
    assert rh._resolve_github_handle(config, {"handle": "@octocat"}) == "octocat"


def test_resolve_github_handle_reads_profile_github_url(config):
    profile = config.profiles_dir / "candidate_profile.json"
    profile.write_text(
        json.dumps({"contact": {"github_url": "https://github.com/torvalds/"}}),
        encoding="utf-8",
    )
    assert rh._resolve_github_handle(config, {}) == "torvalds"


def test_resolve_github_handle_rejects_invalid_chars(config):
    # A handle with a slash/path injection attempt is rejected.
    assert rh._resolve_github_handle(config, {"handle": "evil/../../x"}) == ""


def test_resolve_github_handle_empty_when_no_profile(config):
    assert rh._resolve_github_handle(config, {}) == ""


# --- _search_links -------------------------------------------------------


def test_search_links_returns_groups_and_counts():
    result = rh._search_links({"query": "ml engineer", "location": "Paris"})
    assert result["query_count"] == len(result["groups"])
    assert result["link_count"] == sum(len(g["links"]) for g in result["groups"])
    assert "generated_at" in result


# --- _save_jobs ----------------------------------------------------------


def test_save_jobs_records_packet_failure(config, monkeypatch):
    # Arrange: every job is "created"; packet prep raises -> failures recorded.
    job = _job()
    monkeypatch.setattr(rh, "add_job_to_tracker", lambda cfg, j: (j, True))
    monkeypatch.setattr(rh, "job_to_dict", lambda j, packet=None: {"id": j.id, "packet": packet})

    def boom(*a, **k):
        raise RuntimeError("latex missing")

    monkeypatch.setattr(rh, "generate_packet_for_job", boom)

    # Act
    result = rh._save_jobs(config, [job], prepare_packets=True, force_packets=False)

    # Assert
    assert result["imported"] == 1
    assert result["prepared"] == 0
    assert len(result["failures"]) == 1
    assert "latex missing" in result["failures"][0]


def test_save_jobs_counts_duplicates(config, monkeypatch):
    job = _job()
    monkeypatch.setattr(rh, "add_job_to_tracker", lambda cfg, j: (j, False))
    monkeypatch.setattr(rh, "job_to_dict", lambda j, packet=None: {"id": j.id})
    monkeypatch.setattr(rh, "_latest_packet_for_job", lambda db, jid: None)

    result = rh._save_jobs(config, [job], prepare_packets=False, force_packets=False)
    assert result["duplicates"] == 1
    assert result["imported"] == 0


# --- _api_search ---------------------------------------------------------


def test_api_search_without_save_returns_serialized_jobs(config, monkeypatch):
    jobs = [_job("J1"), _job("J2")]
    monkeypatch.setattr(rh, "search_free_api_jobs", lambda *a, **k: jobs)
    monkeypatch.setattr(rh, "job_to_dict", lambda j, packet=None: {"title": j.title})

    result = rh._api_search(config, {"save": False, "query": "ds"})
    assert result["found"] == 2
    assert result["imported"] == 0
    assert [j["title"] for j in result["jobs"]] == ["J1", "J2"]


def test_api_search_with_save_invokes_save_jobs(config, monkeypatch):
    jobs = [_job("J1")]
    monkeypatch.setattr(rh, "search_free_api_jobs", lambda *a, **k: jobs)
    monkeypatch.setattr(
        rh, "_save_jobs",
        lambda cfg, j, prepare_packets, force_packets: {
            "jobs": [{"saved": True}], "imported": 1, "duplicates": 0, "prepared": 0, "failures": [],
        },
    )
    result = rh._api_search(config, {"save": True, "source": "francetravail"})
    assert result["imported"] == 1
    assert result["source"] == "francetravail"


# --- _enrich_batch -------------------------------------------------------


def test_enrich_batch_records_per_job_errors(config, monkeypatch):
    def fake_enrich(cfg, job_id, options):
        if job_id == "bad":
            raise ValueError("enrich failed")
        return {"sources": ["rome"]}

    monkeypatch.setattr(rh, "enrich_job", fake_enrich)
    result = rh._enrich_batch(config, {"job_ids": ["good", "bad"]})
    assert result["count"] == 2
    statuses = {r["job_id"]: r["ok"] for r in result["results"]}
    assert statuses == {"good": True, "bad": False}


# --- _multi_source_search: source parsing variants -----------------------


def test_multi_source_search_defaults_sources_when_absent(config, monkeypatch):
    captured: dict = {}

    def fake_all(**kwargs):
        captured.update(kwargs)
        return {"jobs": [], "per_source": {}, "errors": {}}

    monkeypatch.setattr(rh, "search_all_free_sources", fake_all)
    result = rh._multi_source_search(config, {"save": False})
    # No "sources" provided -> KEYWORD_ONLY_SOURCES default used.
    assert captured["sources"] == list(rh.KEYWORD_ONLY_SOURCES)
    assert result["found"] == 0


def test_multi_source_search_parses_list_sources(config, monkeypatch):
    monkeypatch.setattr(
        rh, "search_all_free_sources",
        lambda **k: {"jobs": [], "per_source": {}, "errors": {}},
    )
    result = rh._multi_source_search(
        config, {"save": False, "sources": ["remoteok", "  ", "arbeitnow"]}
    )
    assert result["sources"] == ["remoteok", "arbeitnow"]


def test_multi_source_search_floors_min_relevance_at_20(config, monkeypatch):
    captured: dict = {}

    def fake_all(**kwargs):
        captured.update(kwargs)
        return {"jobs": [], "per_source": {}, "errors": {}}

    monkeypatch.setattr(rh, "search_all_free_sources", fake_all)

    # Client sends 0 (or omits it) -> floored to 20 so one-token noise is dropped.
    rh._multi_source_search(config, {"save": False, "min_relevance": 0})
    assert captured["min_relevance"] == 20

    # A higher caller value is respected, not lowered.
    rh._multi_source_search(config, {"save": False, "min_relevance": 80})
    assert captured["min_relevance"] == 80


# --- _one_click_hunt -----------------------------------------------------


def test_one_click_hunt_falls_back_to_manual_when_api_unconfigured(config, monkeypatch):
    # Arrange: France Travail not configured -> curated manual links branch.
    monkeypatch.setattr(rh, "is_france_travail_configured", lambda: False)
    monkeypatch.setattr(
        rh, "load_profile_bundle",
        lambda cfg: (_StubProfile(), object(), None),
    )
    monkeypatch.setattr(rh, "suggest_search_queries", lambda *a, **k: {"queries": ["ds paris"], "used_ai": False})

    # Act
    result = rh._one_click_hunt(config, {"query": "data scientist"})

    # Assert
    assert result["api_configured"] is False
    assert result["jobs"] == []
    assert "manual" in result


def test_one_click_hunt_uses_deterministic_plan_when_profile_load_fails(config, monkeypatch):
    monkeypatch.setattr(rh, "is_france_travail_configured", lambda: False)

    def boom(cfg):
        raise RuntimeError("no profile")

    monkeypatch.setattr(rh, "load_profile_bundle", boom)
    result = rh._one_click_hunt(config, {"query": "ml"})
    assert result["api_configured"] is False
    # The deterministic fallback plan is surfaced.
    assert result["query_plan"]["used_ai"] is False


def test_one_click_hunt_searches_api_when_configured(config, monkeypatch):
    monkeypatch.setattr(rh, "is_france_travail_configured", lambda: True)
    monkeypatch.setattr(rh, "load_profile_bundle", lambda cfg: (_StubProfile(), object(), None))
    monkeypatch.setattr(rh, "suggest_search_queries", lambda *a, **k: {"queries": ["q1"], "used_ai": True})
    monkeypatch.setattr(rh, "search_free_api_jobs", lambda *a, **k: [_job("FT job")])
    monkeypatch.setattr(rh, "search_all_free_sources", lambda **k: {"jobs": [], "per_source": {}, "errors": {}})
    monkeypatch.setattr(
        rh, "_save_jobs",
        lambda cfg, j, prepare_packets, force_packets: {
            "jobs": [{"x": 1}] * len(j), "imported": len(j), "duplicates": 0, "prepared": 0, "failures": [],
        },
    )

    result = rh._one_click_hunt(config, {"query": "ds", "include_multi_source": True})
    assert result["api_configured"] is True
    assert result["imported"] >= 1
    assert result["multi_source"] is not None


# --- _export_internships -------------------------------------------------


def test_export_internships_returns_workbook_and_count(config, monkeypatch):
    monkeypatch.setattr(
        rh, "export_applied_internships",
        lambda cfg, workbook_path, sheet_name: (Path("/tmp/out.xlsx"), 3),
    )
    result = rh._export_internships(config, {"workbook": "out.xlsx"})
    assert result["count"] == 3
    assert "out.xlsx" in result["workbook"]


class _StubProfile:
    def all_skill_names(self):
        return ["python"]
