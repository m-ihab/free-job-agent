import json

from click.testing import CliRunner

from job_agent.cli.main import app
from job_agent.intake.france_market import build_france_search_urls, cac40_targets, expand_france_search_queries


def test_france_search_urls_include_major_boards():
    rows = build_france_search_urls("data science stage", "Paris")
    keys = {row[0] for row in rows}
    assert "welcome-to-the-jungle" in keys
    assert "hellowork" in keys
    assert "apec" in keys
    assert "france-travail-web" in keys
    assert any("data+science+stage" in row[2] for row in rows)


def test_cac40_targets_include_bnp_and_schneider():
    names = {target.name for target in cac40_targets()}
    assert "BNP Paribas" in names
    assert "Schneider Electric" in names
    assert "TotalEnergies" in names


def test_expand_france_search_queries_includes_bilingual_contract_terms():
    queries = expand_france_search_queries("data scientist", limit=20)
    lowered = {query.lower() for query in queries}
    assert "data scientist stage" in lowered
    assert "data scientist internship" in lowered
    assert "data scientist alternance" in lowered
    assert "data scientist stagiaire" in lowered


def test_expand_france_search_queries_can_select_language():
    english = expand_france_search_queries("data scientist", limit=10, language="english")
    french = expand_france_search_queries("data scientist", limit=10, language="french")
    both = expand_france_search_queries("data scientist", limit=10, language="both")

    assert "data scientist internship" in {query.lower() for query in english}
    assert "data scientist stage" not in {query.lower() for query in english}
    assert "data scientist stage" in {query.lower() for query in french}
    assert "data scientist internship" not in {query.lower() for query in french}
    assert both.index("data scientist internship") < both.index("data scientist stage")


def test_cli_france_search_urls_runs():
    result = CliRunner().invoke(app, ["france-search-urls", "--query", "machine learning stage", "--location", "Paris"])
    assert result.exit_code == 0, result.output
    assert "Welcome to the Jungle" in result.output
    assert "France Travail" in result.output
    assert "https://www.welcometothejungle.com/fr/jobs?query=machine+learning+stage&aroundQuery=Paris" in result.output
    assert "https://candidat.francetravail.fr/offres/recherche?motsCles=machine+learning+stage&lieux=75D" in result.output
    assert "…" not in result.output


def test_cli_france_search_urls_supports_table_format():
    result = CliRunner().invoke(
        app,
        ["france-search-urls", "--query", "machine learning stage", "--location", "Paris", "--single-query", "--format", "table"],
    )
    assert result.exit_code == 0, result.output
    assert "France search URLs" in result.output


def test_cli_france_search_urls_json_is_machine_readable():
    result = CliRunner().invoke(
        app,
        ["france-search-urls", "--query", "machine learning stage", "--location", "Paris", "--single-query", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert rows[0]["url"] == "https://candidat.francetravail.fr/offres/recherche?motsCles=machine+learning+stage&lieux=75D"


def test_cli_france_targets_runs():
    result = CliRunner().invoke(app, ["france-targets", "--limit", "3"])
    assert result.exit_code == 0, result.output
    assert "Accor" in result.output
