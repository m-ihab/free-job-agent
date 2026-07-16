"""Evidence-linked payload tests for the score explanation route."""
from __future__ import annotations

import sqlite3
from typing import Any

from job_agent.schemas.job import JobListing
from job_agent.ui.routes import post_score_explain as route


class _EvidenceDB:
    def __init__(self, rows: list[dict[str, Any]] | None = None, *, missing: bool = False) -> None:
        self.rows = rows or []
        self.missing = missing

    def list_evidence_items_with_ids(self) -> list[dict[str, Any]]:
        if self.missing:
            raise sqlite3.OperationalError("no such table: evidence_items")
        return self.rows

    def list_feedback(self) -> list[dict[str, Any]]:
        return []


class _Tracker:
    def __init__(self, job: JobListing, db: _EvidenceDB) -> None:
        self.job = job
        self.db = db

    def get_job(self, job_id: str) -> JobListing | None:
        return self.job if job_id == self.job.id else None


class _Handler:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def _config(self) -> object:
        return object()

    def _send_json(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def _send_error_json(self, message: str) -> None:
        raise AssertionError(message)


def _explain(
    monkeypatch: Any,
    sample_profile: Any,
    db: _EvidenceDB,
) -> dict[str, Any]:
    job = JobListing(
        title="Data Scientist",
        company="ACME",
        location="Paris",
        source="paste",
        tech_stack=["Python", "SQL"],
        languages=["French"],
    )
    tracker = _Tracker(job, db)
    monkeypatch.setattr(route, "_tracker", lambda config: tracker)
    monkeypatch.setattr(
        route,
        "load_profile_bundle",
        lambda config: (sample_profile, None, None),
    )
    monkeypatch.setattr(route.embeddings, "semantic_similarity", lambda job, profile, db: None)
    handler = _Handler()

    route.post_score_explain(handler, {"job_id": job.id})

    assert handler.payload is not None
    return handler.payload["explain"]


def test_api_payload_links_components_to_concrete_evidence(monkeypatch: Any, sample_profile: Any) -> None:
    explain = _explain(
        monkeypatch,
        sample_profile,
        _EvidenceDB(
            [
                {
                    "id": 17,
                    "kind": "skill",
                    "label": "Python",
                    "value": "programming; 2 years",
                    "source": "profile",
                    "source_ref": "candidate_profile.skills",
                    "confidence": 1.0,
                },
                {
                    "id": 23,
                    "kind": "language",
                    "label": "French",
                    "value": "French",
                    "source": "profile",
                    "source_ref": "candidate_profile.languages",
                    "confidence": 1.0,
                },
            ]
        ),
    )

    assert all({"evidence", "evidence_label"} <= component.keys() for component in explain["components"])
    skill = next(component for component in explain["components"] if component["name"] == "skill")
    assert skill["evidence"] == [
        {
            "id": 17,
            "snippet": "Python — programming; 2 years",
            "source": "candidate_profile.skills",
        }
    ]
    language = next(component for component in explain["components"] if component["name"] == "language")
    assert language["evidence"][0]["id"] == 23


def test_api_payload_is_honest_when_components_have_no_evidence(
    monkeypatch: Any,
    sample_profile: Any,
) -> None:
    explain = _explain(monkeypatch, sample_profile, _EvidenceDB())

    for component in explain["components"]:
        assert component["evidence"] == []
        assert component["evidence_label"] == "No supporting evidence found in the evidence store."


def test_api_payload_fails_soft_when_evidence_store_is_missing(
    monkeypatch: Any,
    sample_profile: Any,
) -> None:
    explain = _explain(monkeypatch, sample_profile, _EvidenceDB(missing=True))

    assert explain["components"]
    for component in explain["components"]:
        assert component["evidence"] == []
        assert component["evidence_label"] == "Evidence store unavailable; no evidence linked."
