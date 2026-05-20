"""Tests for the CLI."""
from click.testing import CliRunner

from job_agent.cli.main import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "job-agent" in result.output.lower() or "Usage" in result.output


def test_list_no_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No jobs" in result.output


def test_init_command(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "Initialized" in result.output


def test_add_subcommand_help():
    result = runner.invoke(app, ["add", "--help"])
    assert result.exit_code == 0


def test_status_invalid_status(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["status", "fakeid", "INVALID_STATUS"])
    assert result.exit_code != 0
    assert "Unknown status" in result.output
