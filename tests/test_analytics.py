"""Tests for local analytics over the application database.

Focus on the invariants that silently corrupt the dashboard if broken:
funnel monotonicity, ISO parsing edge cases, zero-division guards, score
bucket boundaries, and CSV shape/quoting.
"""
from __future__ import annotations

from datetime import datetime, timezone

from job_agent.analytics import (
    _parse_iso,
    _week_key,
    compute_stats,
    export_jobs_csv,
    jobs_to_csv,
)
from job_agent.schemas.job import JobListing, JobStatus


def _make_job(**overrides) -> JobListing:
    base = dict(title="Data Scientist", company="ACME", source="paste")
    base.update(overrides)
    return JobListing(**base)


# --- _parse_iso -----------------------------------------------------------

def test_parse_iso_handles_zulu_suffix():
    parsed = _parse_iso("2026-01-02T03:04:05Z")
    assert parsed == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_parse_iso_returns_none_for_empty_or_garbage():
    assert _parse_iso(None) is None
    assert _parse_iso("") is None
    assert _parse_iso("not-a-date") is None


def test_week_key_formats_iso_week():
    key = _week_key(datetime(2026, 1, 5, tzinfo=timezone.utc))  # Monday, ISO W02
    assert key == "2026-W02"


# --- compute_stats funnel -------------------------------------------------

def test_compute_stats_empty_db_has_zero_total_and_one_week_row(tmp_db):
    stats = compute_stats(tmp_db)

    assert stats["total"] == 0
    assert len(stats["weekly"]) == 1  # always at least the current week
    assert stats["funnel"][0] == {"label": "Tracked", "count": 0}


def test_compute_stats_funnel_is_monotonically_non_increasing(tmp_db):
    tmp_db.save_job(_make_job(status=JobStatus.SCORED))
    tmp_db.save_job(_make_job(status=JobStatus.APPLIED, company="B"))
    tmp_db.save_job(_make_job(status=JobStatus.INTERVIEW, company="C"))

    counts = [stage["count"] for stage in compute_stats(tmp_db)["funnel"]]

    assert counts[0] == 3  # Tracked == total
    assert counts == sorted(counts, reverse=True)  # later stages never exceed earlier


def test_compute_stats_later_status_implies_earlier_funnel_stage(tmp_db):
    # A single INTERVIEW job must count toward Scored, Submitted, and Interview+.
    tmp_db.save_job(_make_job(status=JobStatus.INTERVIEW))

    funnel = {stage["label"]: stage["count"] for stage in compute_stats(tmp_db)["funnel"]}

    assert funnel["Scored"] == 1
    assert funnel["Submitted"] == 1
    assert funnel["Interview+"] == 1
    assert funnel["Offer"] == 0


# --- compute_stats guards & buckets --------------------------------------

def test_compute_stats_response_rate_is_zero_when_nothing_submitted(tmp_db):
    tmp_db.save_job(_make_job(status=JobStatus.SCORED, fit_score=80))

    stats = compute_stats(tmp_db)

    assert stats["submitted_count"] == 0
    assert stats["response_rate"] == 0.0  # no ZeroDivisionError


def test_compute_stats_avg_score_is_none_without_scored_jobs(tmp_db):
    tmp_db.save_job(_make_job(fit_score=None))

    assert compute_stats(tmp_db)["avg_score"] is None


def test_compute_stats_score_buckets_use_inclusive_lower_bounds(tmp_db):
    for score in (49, 50, 69, 70, 84, 85):
        tmp_db.save_job(_make_job(fit_score=score, company=f"C{score}"))

    buckets = compute_stats(tmp_db)["score_buckets"]

    assert buckets == {"0-49": 1, "50-69": 2, "70-84": 2, "85-100": 1}


def test_compute_stats_response_rate_reflects_interviews_over_submitted(tmp_db):
    tmp_db.save_job(_make_job(status=JobStatus.APPLIED, company="A"))
    tmp_db.save_job(_make_job(status=JobStatus.INTERVIEW, company="B"))

    stats = compute_stats(tmp_db)

    assert stats["submitted_count"] == 2
    assert stats["interview_count"] == 1
    assert stats["response_rate"] == 50.0


# --- jobs_to_csv ----------------------------------------------------------

def test_jobs_to_csv_has_header_and_one_row_per_job():
    csv_text = jobs_to_csv([_make_job(), _make_job(company="B")])
    rows = csv_text.strip().splitlines()

    assert rows[0].startswith("id,title,company,location")
    assert len(rows) == 3  # header + 2 jobs


def test_jobs_to_csv_quotes_embedded_commas():
    row = jobs_to_csv([_make_job(title="DS, Senior")]).splitlines()[1]

    assert '"DS, Senior"' in row


def test_jobs_to_csv_renders_remote_flag_and_blank_score():
    csv_text = jobs_to_csv([_make_job(remote=True, fit_score=None)])
    data_row = csv_text.splitlines()[1].split(",")

    assert "yes" in data_row  # remote rendered as yes/no, not True/False


def test_jobs_to_csv_falls_back_to_source_url_for_apply_link():
    csv_text = jobs_to_csv([_make_job(apply_url=None, source_url="https://src/job")])

    assert "https://src/job" in csv_text


# --- export_jobs_csv ------------------------------------------------------

def test_export_jobs_csv_writes_file_and_creates_parents(tmp_db, tmp_path):
    tmp_db.save_job(_make_job())
    out = tmp_path / "nested" / "jobs.csv"

    result = export_jobs_csv(tmp_db, out)

    assert result == out
    assert out.exists()
    assert "Data Scientist" in out.read_text(encoding="utf-8")
