"""Deterministic thumbs feedback storage, ranking, CLI, and dashboard seams."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from job_agent.cli.main import app
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.feedback import (
    FeedbackRecord,
    aggregate_feedback,
    calculate_feedback_adjustment,
    rank_jobs_with_feedback,
    record_feedback,
)
from job_agent.schemas.job import JobListing
from job_agent.ui.routes import POST_ROUTES
from job_agent.ui.routes.post_feedback import post_feedback


def _feedback(
    index: int,
    verdict: str,
    *,
    company: str = "Acme",
    keywords: tuple[str, ...] = ("data", "scientist"),
    source: str = "france-travail",
) -> FeedbackRecord:
    return FeedbackRecord(
        job_id=f"job-{index}",
        verdict=verdict,
        created_at=f"2026-07-14T00:00:{index:02d}Z",
        company=company,
        title_keywords=keywords,
        source=source,
    )


def test_feedback_storage_crud_captures_job_snapshot(
    tmp_db: Database, sample_job: JobListing
) -> None:
    tmp_db.save_job(sample_job)

    saved = record_feedback(tmp_db, sample_job.id, "up")

    fetched = tmp_db.get_feedback(sample_job.id)
    assert fetched == saved
    assert fetched is not None
    assert fetched.company == "TechCorp Inc."
    assert fetched.source == "paste"
    assert {"python", "engineer"} <= set(fetched.title_keywords)
    assert tmp_db.list_feedback() == [fetched]

    assert tmp_db.delete_feedback(sample_job.id) is True
    assert tmp_db.get_feedback(sample_job.id) is None


def test_rerating_updates_existing_feedback_row_idempotently(
    tmp_db: Database, sample_job: JobListing
) -> None:
    tmp_db.save_job(sample_job)
    record_feedback(tmp_db, sample_job.id, "up")

    updated = record_feedback(tmp_db, sample_job.id, "down")

    assert updated.verdict == "down"
    assert len(tmp_db.list_feedback()) == 1
    assert tmp_db.get_feedback(sample_job.id) == updated


def test_record_feedback_rejects_unknown_jobs_and_verdicts(tmp_db: Database) -> None:
    with pytest.raises(ValueError, match="Job not found"):
        record_feedback(tmp_db, "missing", "up")

    job = JobListing(title="Data Analyst", company="Acme")
    tmp_db.save_job(job)
    with pytest.raises(ValueError, match="up.*down"):
        record_feedback(tmp_db, job.id, "maybe")


def test_aggregate_feedback_counts_company_title_and_source_votes() -> None:
    aggregates = aggregate_feedback(
        [
            _feedback(1, "up"),
            _feedback(2, "up"),
            _feedback(3, "down", keywords=("data", "engineer")),
        ]
    )

    assert aggregates.companies["acme"].up == 2
    assert aggregates.companies["acme"].down == 1
    assert aggregates.title_keywords["scientist"].net == 2
    assert aggregates.title_keywords["engineer"].net == -1
    assert aggregates.sources["france-travail"].net == 1


@pytest.mark.parametrize(
    ("verdict", "expected_adjustment"),
    [("up", 5), ("down", -5)],
)
def test_feedback_adjustment_is_bounded_to_five_points(
    verdict: str, expected_adjustment: int
) -> None:
    records = [_feedback(index, verdict) for index in range(10)]
    target = JobListing(
        title="Data Scientist",
        company="Acme",
        source="france-travail",
        fit_score=70,
    )

    result = calculate_feedback_adjustment(target, aggregate_feedback(records), base_score=70)

    assert result.adjustment == expected_adjustment
    assert result.adjusted_score == 70 + expected_adjustment
    assert abs(result.adjustment) <= 5


def test_feedback_explanation_names_company_vote_count() -> None:
    records = [
        _feedback(1, "down", keywords=("analytics",), source="manual"),
        _feedback(2, "down", keywords=("engineering",), source="other"),
    ]
    target = JobListing(title="Machine Learning Intern", company="Acme", source="greenhouse")

    result = calculate_feedback_adjustment(target, aggregate_feedback(records), base_score=80)

    assert result.company_adjustment == -2
    assert "2 downvotes for this company" in result.reasons


def test_feedback_ranking_uses_adjusted_score_without_mutating_base_scores() -> None:
    records = [_feedback(1, "up", company="Acme", keywords=("ml", "engineer"))]
    preferred = JobListing(
        title="ML Engineer",
        company="Acme",
        source="france-travail",
        fit_score=70,
    )
    other = JobListing(title="Data Engineer", company="Other", source="manual", fit_score=72)

    ranked = rank_jobs_with_feedback([other, preferred], records)

    assert ranked[0].job is preferred
    assert ranked[0].adjusted_score == 73
    assert preferred.fit_score == 70
    assert other.fit_score == 72


def test_cli_records_and_lists_feedback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    config = AppConfig.load()
    config.ensure_dirs()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = JobListing(title="Data Analyst", company="Acme", source="manual")
    db.save_job(job)
    runner = CliRunner()

    rated = runner.invoke(app, ["feedback", job.id, "--up"])
    listed = runner.invoke(app, ["feedback", "--list"])

    assert rated.exit_code == 0
    assert "thumbs up" in rated.output.lower()
    assert listed.exit_code == 0
    assert job.id[:8] in listed.output
    assert "up" in listed.output.lower()


class _FeedbackHandler:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.payload: dict[str, Any] | None = None

    def _config(self) -> AppConfig:
        return self.config

    def _send_json(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def _send_error_json(self, message: str, status: Any = None) -> None:
        raise AssertionError(f"Unexpected route error: {message} ({status})")


def test_dashboard_feedback_route_and_static_module(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        data_dir=tmp_path / "data",
        profiles_dir=tmp_path / "profiles",
        outputs_dir=tmp_path / "outputs",
    )
    config.ensure_dirs()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = JobListing(title="Data Analyst", company="Acme", source="manual", fit_score=70)
    db.save_job(job)
    handler = _FeedbackHandler(config)

    post_feedback(handler, {"job_id": job.id, "verdict": "down"})

    assert "/api/feedback" in POST_ROUTES
    assert handler.payload is not None
    assert handler.payload["feedback"]["verdict"] == "down"
    static_dir = Path(__file__).parents[1] / "src" / "job_agent" / "ui" / "static"
    assert "data-feedback" in (static_dir / "feedback.js").read_text(encoding="utf-8")
    assert (
        "feedback adjustment"
        in (static_dir / "score_explain.js").read_text(encoding="utf-8").lower()
    )
