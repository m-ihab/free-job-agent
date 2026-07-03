"""Tests for credential-less career-page discovery via ATS slug probing."""
from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.db.database import Database
from job_agent.intake import discovery


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


# ---- slug generation ----

def test_slug_candidates_normalizes_accents_and_punctuation() -> None:
    slugs = discovery.slug_candidates("L'Oréal")
    assert "loreal" in slugs


def test_slug_candidates_multi_word_variants() -> None:
    slugs = discovery.slug_candidates("Dataiku Labs")
    assert "dataiku-labs" in slugs
    assert "dataikulabs" in slugs
    assert "dataiku" in slugs


def test_slug_candidates_empty_company_is_empty() -> None:
    assert discovery.slug_candidates("") == []
    assert discovery.slug_candidates("  !!  ") == []


# ---- probing with fake transport ----

class _FakeTransport:
    """Maps URL substrings to status codes; records every probed URL."""

    def __init__(self, hits: dict[str, int]) -> None:
        self.hits = hits
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: int) -> int:
        self.calls.append(url)
        for fragment, status in self.hits.items():
            if fragment in url:
                return status
        return 404


def test_discover_company_boards_saves_hits(db: Database) -> None:
    transport = _FakeTransport({"boards-api.greenhouse.io/v1/boards/dataiku": 200})
    found = discovery.discover_company_boards(
        db, "Dataiku", transport=transport, sleep=lambda s: None,
    )
    assert any(b["source"] == "greenhouse" and b["slug"] == "dataiku" for b in found)
    saved = db.list_company_boards()
    assert any(b["source"] == "greenhouse" and b["slug"] == "dataiku" for b in saved)


def test_discover_company_boards_upsert_no_duplicates(db: Database) -> None:
    transport = _FakeTransport({"boards-api.greenhouse.io/v1/boards/dataiku": 200})
    discovery.discover_company_boards(db, "Dataiku", transport=transport, sleep=lambda s: None)
    discovery.discover_company_boards(db, "Dataiku", transport=transport, sleep=lambda s: None)
    boards = [b for b in db.list_company_boards() if b["source"] == "greenhouse"]
    assert len(boards) == 1


def test_discover_negative_results_are_cached(db: Database) -> None:
    transport = _FakeTransport({})  # everything 404s
    discovery.discover_company_boards(db, "NoSuchCorp", transport=transport, sleep=lambda s: None)
    first_call_count = len(transport.calls)
    assert first_call_count > 0
    # Second run: every (source, slug) pair is negative-cached — no new probes.
    discovery.discover_company_boards(db, "NoSuchCorp", transport=transport, sleep=lambda s: None)
    assert len(transport.calls) == first_call_count


def test_discover_boards_batch_summary(db: Database) -> None:
    transport = _FakeTransport({
        "boards-api.greenhouse.io/v1/boards/dataiku": 200,
        "api.lever.co/v0/postings/alan": 200,
    })
    summary = discovery.discover_boards(
        db, ["Dataiku", "Alan"], transport=transport, sleep=lambda s: None,
    )
    assert summary["companies_checked"] == 2
    assert summary["boards_found"] >= 2
    sources = {b["source"] for b in summary["boards"]}
    assert {"greenhouse", "lever"}.issubset(sources)


def test_transport_errors_are_treated_as_miss(db: Database) -> None:
    def _boom(url: str, timeout: int) -> int:
        raise RuntimeError("network down")

    found = discovery.discover_company_boards(db, "Dataiku", transport=_boom, sleep=lambda s: None)
    assert found == []


# ---- DB roundtrip ----

def test_company_boards_roundtrip(db: Database) -> None:
    db.save_company_board("Dataiku", "greenhouse", "dataiku")
    boards = db.list_company_boards()
    assert boards[0]["company"] == "Dataiku"
    assert boards[0]["source"] == "greenhouse"
    assert boards[0]["slug"] == "dataiku"
    # Same (source, slug) upserts rather than duplicating.
    db.save_company_board("Dataiku SAS", "greenhouse", "dataiku")
    assert len(db.list_company_boards()) == 1


# ---- curated seed pack ----

def test_default_target_companies_is_nonempty_and_unique() -> None:
    companies = discovery.default_target_companies()
    assert len(companies) >= 20
    assert len(companies) == len(set(companies))
