"""Obsidian vault exporter: DB jobs -> linked notes + dashboard.

The value of the vault is in the *links*: each job note wikilinks to its
company and skills, so Obsidian's graph surfaces companies and skills as hubs.
These tests lock in that structure (frontmatter, wikilinks, foldering, dashboard)
so the graph stays meaningful.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.exporters.obsidian import (
    _slugify,
    export_obsidian_vault,
)
from job_agent.schemas.job import JobListing, JobStatus


def _jobs() -> list[JobListing]:
    return [
        JobListing(
            title="Data Scientist",
            company="ACME",
            location="Paris",
            remote=False,
            source="linkedin",
            apply_url="https://acme.example/apply",
            tech_stack=["Python", "Machine Learning"],
            status=JobStatus.NEEDS_MANUAL,
            fit_score=82.0,
            raw_text="We need a data scientist.",
        ),
        JobListing(
            title="ML Engineer",
            company="ACME",
            location="Remote",
            remote=True,
            source="greenhouse",
            tech_stack=["Python", "PyTorch"],
            status=JobStatus.PACKET_READY,
            fit_score=74.0,
        ),
    ]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Data Scientist", "data-scientist"),
        ("C++ / Rust!", "c-rust"),
        ("  Machine   Learning  ", "machine-learning"),
        ("", "untitled"),
    ],
)
def test_slugify(raw: str, expected: str) -> None:
    assert _slugify(raw) == expected


def test_export_writes_foldered_notes_and_dashboard(tmp_path: Path) -> None:
    vault, count = export_obsidian_vault(None, vault_path=tmp_path, jobs=_jobs())

    assert count == 2
    assert vault == tmp_path
    assert (tmp_path / "Dashboard.md").exists()
    job_notes = list((tmp_path / "jobs").glob("*.md"))
    assert len(job_notes) == 2
    # Company + skill hub notes are created (ACME appears twice -> one note).
    assert (tmp_path / "companies" / "acme.md").exists()
    assert (tmp_path / "skills" / "python.md").exists()
    assert (tmp_path / "skills" / "pytorch.md").exists()


def test_job_note_has_frontmatter_and_wikilinks(tmp_path: Path) -> None:
    export_obsidian_vault(None, vault_path=tmp_path, jobs=_jobs())
    note = (tmp_path / "jobs" / "data-scientist-acme.md").read_text(encoding="utf-8")

    assert note.startswith("---")          # YAML frontmatter
    assert "status: NEEDS_MANUAL" in note
    assert "score: 82" in note
    assert "[[acme|ACME]]" in note         # company wikilink (body -> graph edge)
    assert "[[python]]" in note            # skill wikilink
    assert "https://acme.example/apply" in note


def test_company_note_backlinks_all_its_jobs(tmp_path: Path) -> None:
    export_obsidian_vault(None, vault_path=tmp_path, jobs=_jobs())
    company = (tmp_path / "companies" / "acme.md").read_text(encoding="utf-8")
    # Both ACME jobs are listed on the company note.
    assert "data-scientist-acme" in company
    assert "ml-engineer-acme" in company
    assert "tags:" in company and "company" in company


def test_dashboard_groups_by_status_and_score(tmp_path: Path) -> None:
    export_obsidian_vault(None, vault_path=tmp_path, jobs=_jobs())
    dash = (tmp_path / "Dashboard.md").read_text(encoding="utf-8")
    assert "NEEDS_MANUAL" in dash
    assert "PACKET_READY" in dash
    assert "[[jobs/data-scientist-acme" in dash  # links into job notes


def test_export_is_idempotent(tmp_path: Path) -> None:
    export_obsidian_vault(None, vault_path=tmp_path, jobs=_jobs())
    vault, count = export_obsidian_vault(None, vault_path=tmp_path, jobs=_jobs())
    # Re-running does not duplicate notes.
    assert count == 2
    assert len(list((tmp_path / "jobs").glob("*.md"))) == 2


def test_export_empty_jobs_still_writes_dashboard(tmp_path: Path) -> None:
    vault, count = export_obsidian_vault(None, vault_path=tmp_path, jobs=[])
    assert count == 0
    assert (tmp_path / "Dashboard.md").exists()


def test_export_from_db_via_tracker(tmp_path: Path, monkeypatch) -> None:
    """Integration: jobs in the SQLite DB are exported when no jobs= is passed."""
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.config import AppConfig
    from job_agent.db.database import Database

    config = AppConfig()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    db.save_job(JobListing(title="NLP Intern", company="Hooli", source="paste",
                           tech_stack=["Python", "spaCy"], status=JobStatus.PACKET_READY))

    vault, count = export_obsidian_vault(config, vault_path=tmp_path / "vault")
    assert count == 1
    assert (tmp_path / "vault" / "companies" / "hooli.md").exists()
    assert (tmp_path / "vault" / "skills" / "spacy.md").exists()
