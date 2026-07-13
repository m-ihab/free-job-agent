"""Hermetic coverage for the curated EU source registry and ATS X-Ray links."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from click.testing import CliRunner

from job_agent.cli.main import app
from job_agent.intake.france_market import board_notes, build_france_search_urls


REGISTRY_PATH = Path(__file__).parents[1] / "src" / "job_agent" / "data" / "eu_sources.json"
ATTRIBUTION = "discovery aided by kitsuno-ai/agentic-job-search-eu (CC-BY-SA 4.0)"
REQUIRED_FIELDS = {
    "id",
    "name",
    "url",
    "countries",
    "access_type",
    "requires_auth",
    "license_posture",
    "notes",
    "added_date",
    "attribution",
    "verified",
}
XRAY_DOMAINS = {
    "xray-greenhouse": "boards.greenhouse.io",
    "xray-lever": "jobs.lever.co",
    "xray-ashby": "jobs.ashbyhq.com",
    "xray-workable": "apply.workable.com",
    "xray-smartrecruiters": "jobs.smartrecruiters.com",
    "xray-workday": "myworkdayjobs.com",
    "xray-recruitee": "recruitee.com",
    "xray-personio": "jobs.personio.com",
}


def test_eu_source_registry_schema() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    assert registry["attribution"] == ATTRIBUTION
    sources = registry["sources"]
    assert 12 <= len(sources) <= 18
    assert len({source["id"] for source in sources}) == len(sources)

    for source in sources:
        assert REQUIRED_FIELDS <= source.keys()
        assert source["verified"] is False
        assert source["access_type"] in {"api", "rss", "manual-links"}
        assert isinstance(source["requires_auth"], bool)
        assert isinstance(source["countries"], list) and source["countries"]
        assert all(isinstance(country, str) and country for country in source["countries"])
        assert all(isinstance(source[field], str) and source[field] for field in REQUIRED_FIELDS - {"countries", "requires_auth", "verified"})
        assert urlsplit(source["url"]).scheme == "https"
        assert urlsplit(source["url"]).netloc
        date.fromisoformat(source["added_date"])


def test_ats_xray_urls_are_manual_google_searches_with_encoded_phrases() -> None:
    rows = build_france_search_urls(
        'machine "learning" & AI',
        "Paris & Lyon",
        boards=list(XRAY_DOMAINS),
    )
    urls = {key: url for key, _name, url in rows}

    assert set(urls) == set(XRAY_DOMAINS)
    for key, domain in XRAY_DOMAINS.items():
        parsed = urlsplit(urls[key])
        assert parsed.scheme == "https"
        assert parsed.netloc == "www.google.com"
        assert parsed.path == "/search"
        assert parse_qs(parsed.query)["q"] == [
            f'site:{domain} "machine learning & AI" "Paris & Lyon"'
        ]
        assert " " not in urls[key]
        assert "%22" in urls[key]
        assert "%26" in urls[key]

    notes = board_notes()
    assert all("manual-open only" in notes[key].casefold() for key in XRAY_DOMAINS)


def test_api_sources_lists_curated_eu_registry() -> None:
    result = CliRunner().invoke(app, ["api-sources"])

    assert result.exit_code == 0
    assert "Curated EU source registry" in result.output
    assert "france_travail" in result.output
    assert "verified=no" in result.output
    assert ATTRIBUTION in result.output
