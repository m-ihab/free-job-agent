from click.testing import CliRunner

from job_agent.cli.main import app
from job_agent.intake.france_market import build_france_search_urls, cac40_targets


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


def test_cli_france_search_urls_runs():
    result = CliRunner().invoke(app, ["france-search-urls", "--query", "machine learning stage", "--location", "Paris"])
    assert result.exit_code == 0, result.output
    assert "Welcome to the Jungle" in result.output
    assert "France Travail" in result.output


def test_cli_france_targets_runs():
    result = CliRunner().invoke(app, ["france-targets", "--limit", "3"])
    assert result.exit_code == 0, result.output
    assert "Accor" in result.output
