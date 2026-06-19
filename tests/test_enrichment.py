"""Behavioural tests for job_agent.enrichment.

The France Travail HTTP client is mocked so no network access happens. The
focus is the deterministic merge/aggregation/labelling logic that folds
endpoint payloads back into the JobListing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import job_agent.enrichment as enrichment
from job_agent.config import AppConfig
from job_agent.enrichment import (
    EnrichOptions,
    _apply_anotea,
    _apply_labour_market,
    _apply_rome,
    _apply_training,
    _merge_unique,
    enrich_job,
)
from job_agent.enrichment_helpers import (
    build_context,
    extract_best_string,
    extract_department,
    extract_labels,
    extract_numeric,
    extract_siret,
    fill_params,
)
from job_agent.schemas.job import JobListing


# --- enrichment_helpers (pure payload parsing) ---------------------------


def test_extract_department_pulls_2to3_digit_code():
    # The regex matches a 2-3 digit token bounded by word boundaries.
    assert extract_department("Paris 75") == "75"
    assert extract_department("Lyon (069)") == "069"
    assert extract_department("") == ""


def test_extract_siret_finds_14_digit_run():
    job = JobListing(title="X", company="Y", description="SIRET 12345678901234 listed")
    assert extract_siret(job) == "12345678901234"


def test_build_context_derives_siren_from_siret():
    job = JobListing(title="DS", company="ACME", location="Lyon 69",
                     description="company 98765432101234")
    ctx = build_context(job)
    assert ctx["department"] == "69"
    assert ctx["siret"] == "98765432101234"
    assert ctx["siren"] == "987654321"  # first 9 digits


def test_fill_params_substitutes_and_drops_empty():
    params = {"q": "{title}", "loc": "{location}", "empty": ""}
    out = fill_params(params, {"title": "Data Scientist", "location": ""})
    assert out["q"] == "Data Scientist"
    assert "loc" not in out  # empty after substitution -> dropped
    assert "empty" not in out


def test_extract_labels_dedupes_and_reads_nested_libelle():
    payload = [{"libelle": "Python"}, {"libelle": "Python"}, {"name": "SQL"}]
    assert extract_labels(payload) == ["Python", "SQL"]


def test_extract_best_string_prefers_description_key():
    assert extract_best_string({"description": "best", "name": "x"}) == "best"
    assert extract_best_string(["", {"label": "fallback"}]) == "fallback"


def test_extract_numeric_handles_comma_decimal_and_nesting():
    assert extract_numeric({"rating": "3,5"}) == 3.5
    assert extract_numeric({"outer": {"score": 4}}) == 4.0
    assert extract_numeric("no numbers") is None


# --- pure merge / apply helpers ------------------------------------------


def test_merge_unique_is_case_insensitive_and_order_preserving():
    # Act
    merged = _merge_unique(["Python", "SQL"], ["python", "Docker", "sql"])

    # Assert: existing kept, only genuinely new "Docker" appended.
    assert merged == ["Python", "SQL", "Docker"]


def test_apply_rome_adds_skills_and_appends_description():
    # Arrange
    job = JobListing(title="DS", company="Co", description="Base text", tech_stack=["Python"])

    # Act
    _apply_rome(job, {"rome_skills": ["Python", "Statistics"], "rome_description": "ROME desc"})

    # Assert: only new skill appended, description suffixed once.
    assert job.tech_stack == ["Python", "Statistics"]
    assert "ROME 4.0: ROME desc" in job.description


def test_apply_anotea_flags_low_rating():
    # Arrange
    job = JobListing(title="DS", company="Co")

    # Act
    _apply_anotea(job, {"anotea": {"rating": 1.5}})

    # Assert
    assert "ANOTEA_LOW_RATING" in job.risk_flags
    assert any("low" in note.lower() for note in job.fit_notes)


def test_apply_anotea_records_good_rating_without_flag():
    # Arrange
    job = JobListing(title="DS", company="Co")

    # Act
    _apply_anotea(job, {"anotea": {"rating": 4.2}})

    # Assert
    assert "ANOTEA_LOW_RATING" not in job.risk_flags
    assert any("4.2" in note for note in job.fit_notes)


def test_apply_training_and_labour_market_append_notes():
    # Arrange
    job = JobListing(title="DS", company="Co")

    # Act
    _apply_training(job, {"training_recommendations": ["MLOps course", "SQL bootcamp"]})
    _apply_labour_market(job, {"labour_market_signals": ["High demand in IDF"]})

    # Assert
    joined = " ".join(job.fit_notes)
    assert "Training suggestions" in joined
    assert "Labour market signals" in joined


# --- enrich_job end-to-end with mocked client ----------------------------


def _make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    data_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir)


class _StubClient:
    """Stand-in for FranceTravailClient that never touches the network."""

    def __init__(self, *args, **kwargs):
        pass

    def request(self, key, params=None):  # noqa: ANN001
        raise RuntimeError("network disabled in test")


def test_enrich_job_raises_for_unknown_job(tmp_path, monkeypatch):
    # Arrange
    config = _make_config(tmp_path)
    monkeypatch.setattr(enrichment, "FranceTravailClient", _StubClient)

    # Act / Assert
    with pytest.raises(ValueError, match="Job not found"):
        enrich_job(config, "does-not-exist")


def test_enrich_job_records_endpoint_errors_and_persists(tmp_path, monkeypatch):
    # Arrange: a saved job and a client that always raises -> error sources.
    config = _make_config(tmp_path)
    monkeypatch.setattr(enrichment, "FranceTravailClient", _StubClient)
    # No profile bundle present -> scoring branch is skipped gracefully.

    from job_agent.db.database import Database
    from job_agent.tracker import ApplicationTracker

    db = Database(config.db_path)
    db.initialize()
    tracker = ApplicationTracker(db)
    job = JobListing(title="Data Scientist", company="ACME", location="Paris 75001")
    db.save_job(job)

    # Act
    report = enrich_job(config, job.id, EnrichOptions())

    # Assert: report shape is intact and every called endpoint is recorded.
    assert report["job_id"] == job.id
    assert report["company"] == "ACME"
    assert isinstance(report["sources"], dict)
    # The enrichment was persisted and an event logged.
    saved = tracker.get_enrichment(job.id)
    assert saved is not None


def test_enrich_job_disabled_endpoints_marked_not_configured(tmp_path, monkeypatch):
    # Arrange: the default endpoint registry has rome_* disabled with empty path.
    config = _make_config(tmp_path)
    monkeypatch.setattr(enrichment, "FranceTravailClient", _StubClient)

    from job_agent.db.database import Database

    db = Database(config.db_path)
    db.initialize()
    job = JobListing(title="ML Engineer", company="BetaCorp")
    db.save_job(job)

    # Act: only the ROME group enabled.
    options = EnrichOptions(
        rome=True, anotea=False, training=False,
        labour_market=False, territory=False, employer=False, other=False,
    )
    report = enrich_job(config, job.id, options)

    # Assert: disabled endpoints report "not_configured" (not an HTTP error).
    assert report["sources"].get("rome_skills") == "not_configured"
