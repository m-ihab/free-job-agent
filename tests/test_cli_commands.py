"""Behavioural tests for the CLI command handlers.

Drives ``job_agent.cli.main.app`` (the stdlib-backed ``LocalCLIApp``) through the
local ``click.testing.CliRunner`` shim. All data/profile/output directories are
redirected to a temp path via env vars, and every network / LLM / browser call is
mocked. Assertions cover command output, DB side effects, and error handling.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from job_agent.cli.main import app
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket, PacketStatus
from job_agent.tracker import ApplicationTracker

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
runner = CliRunner()


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch):
    """Redirect all app dirs to a temp path and copy example profiles.

    Yields an initialized ``AppConfig`` so tests can seed the DB directly.
    """
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    outputs_dir = tmp_path / "outputs"
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(profiles_dir))
    monkeypatch.setenv("JOB_AGENT_OUTPUTS_DIR", str(outputs_dir))
    config = AppConfig(data_dir=data_dir, profiles_dir=profiles_dir, outputs_dir=outputs_dir)
    config.ensure_dirs()
    Database(config.db_path).initialize()
    for name in ("candidate_profile.json", "master_cv.json", "master_qa_profile.json"):
        shutil.copyfile(EXAMPLES_DIR / name, profiles_dir / name)
    return config


def _seed_job(config: AppConfig, title="Data Scientist", company="Acme", status=JobStatus.NEW) -> JobListing:
    db = Database(config.db_path)
    job = JobListing(title=title, company=company, source="paste",
                     raw_text=f"{title} at {company}", description="Build ML models in Python.")
    db.save_job(job)
    if status != JobStatus.NEW:
        db.update_job_status(job.id, status)
    return job


# ── jobs: list / show / score / status / delete / history ────────────────────

def test_list_empty_reports_no_jobs(cli_env):
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No jobs" in result.output


def test_list_shows_seeded_job(cli_env):
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert job.id[:8] in result.output
    assert "Acme" in result.output


def test_show_displays_job_details(cli_env):
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["show", job.id])
    assert result.exit_code == 0
    assert "Data Scientist" in result.output
    assert "Acme" in result.output


def test_show_unknown_job_fails(cli_env):
    result = runner.invoke(app, ["show", "missing-id"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_score_sets_status_to_scored(cli_env):
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["score", job.id])
    assert result.exit_code == 0
    assert "Total Score" in result.output
    assert Database(cli_env.db_path).get_job(job.id).status == JobStatus.SCORED


def test_status_updates_job(cli_env):
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["status", job.id, "INTERVIEW"])
    assert result.exit_code == 0
    assert Database(cli_env.db_path).get_job(job.id).status == JobStatus.INTERVIEW


def test_status_invalid_value_fails(cli_env):
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["status", job.id, "NONSENSE"])
    assert result.exit_code != 0
    assert "Unknown status" in result.output


def test_delete_job_requires_yes_flag(cli_env):
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["delete-job", job.id])
    assert result.exit_code == 0
    assert "Refusing to delete" in result.output
    assert Database(cli_env.db_path).get_job(job.id) is not None


def test_delete_job_with_yes_removes_it(cli_env):
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["delete-job", job.id, "--yes"])
    assert result.exit_code == 0
    assert Database(cli_env.db_path).get_job(job.id) is None


def test_history_lists_events(cli_env):
    job = _seed_job(cli_env)
    ApplicationTracker(Database(cli_env.db_path)).update_status(job.id, JobStatus.SCORED)
    result = runner.invoke(app, ["history", job.id])
    assert result.exit_code == 0
    assert "STATUS_CHANGED" in result.output


# ── search / discovery (network mocked) ──────────────────────────────────────

def test_search_api_no_results_reports_empty(cli_env, monkeypatch):
    from job_agent.cli import main
    monkeypatch.setattr(main, "search_free_api_jobs", lambda *a, **k: [])
    result = runner.invoke(app, ["search-api", "remotive", "--query", "data"])
    assert result.exit_code == 0
    assert "No jobs found" in result.output


def test_search_api_saves_results(cli_env, monkeypatch):
    from job_agent.cli import main
    fake = JobListing(title="Data Scientist", company="Acme", source="api:remotive",
                      raw_text="x", apply_url="https://x/1")
    monkeypatch.setattr(main, "search_free_api_jobs", lambda *a, **k: [fake])
    result = runner.invoke(app, ["search-api", "remotive", "--query", "data", "--save"])
    assert result.exit_code == 0
    assert "Saved 1 new jobs" in result.output


def test_search_api_handles_source_error(cli_env, monkeypatch):
    from job_agent.cli import main
    from job_agent.intake.free_apis import FreeApiError

    def _raise(*a, **k):
        raise FreeApiError("bad source")
    monkeypatch.setattr(main, "search_free_api_jobs", _raise)
    result = runner.invoke(app, ["search-api", "remotive"])
    assert result.exit_code != 0
    assert "API search error" in result.output


def test_api_sources_lists_supported(cli_env):
    result = runner.invoke(app, ["api-sources"])
    assert result.exit_code == 0
    assert "remotive" in result.output


# ── apply / packet (pipeline mocked) ─────────────────────────────────────────

def test_apply_generates_packet(cli_env, monkeypatch):
    from job_agent.cli.commands import apply as apply_cmds
    job = _seed_job(cli_env)
    packet = ApplicationPacket(id="pkt_test", job_id=job.id, status=PacketStatus.READY,
                               tailored_cv_pdf_path="cv.pdf", cover_letter_pdf_path="cl.pdf")
    monkeypatch.setattr(apply_cmds, "generate_packet_for_job", lambda *a, **k: packet)
    result = runner.invoke(app, ["apply", job.id])
    assert result.exit_code == 0
    assert "pkt_test" in result.output


def test_apply_reports_failure(cli_env, monkeypatch):
    from job_agent.cli.commands import apply as apply_cmds

    def _boom(*a, **k):
        raise RuntimeError("compile failed")
    monkeypatch.setattr(apply_cmds, "generate_packet_for_job", _boom)
    result = runner.invoke(app, ["apply", "some-job"])
    assert result.exit_code != 0
    assert "Cannot generate packet" in result.output


def test_mark_submitted_updates_packet_and_job(cli_env):
    job = _seed_job(cli_env)
    db = Database(cli_env.db_path)
    packet = ApplicationPacket(id="pkt_sub", job_id=job.id, status=PacketStatus.READY)
    db.save_packet(packet)
    result = runner.invoke(app, ["mark-submitted", packet.id])
    assert result.exit_code == 0
    assert db.get_job(job.id).status == JobStatus.MANUALLY_SUBMITTED
    assert db.get_packet(packet.id).status == PacketStatus.MANUALLY_SUBMITTED


def test_mark_submitted_unknown_packet_fails(cli_env):
    result = runner.invoke(app, ["mark-submitted", "missing"])
    assert result.exit_code != 0
    assert "Packet not found" in result.output


def test_packet_show_reports_none_when_absent(cli_env):
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["packet", "show", job.id])
    assert result.exit_code == 0
    assert "No packet found" in result.output


# ── outreach / market (generators are deterministic, no network) ─────────────

def test_outreach_prints_email_for_known_job(cli_env):
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["outreach", job.id])
    assert result.exit_code == 0
    assert result.output.strip()


def test_outreach_unknown_job_fails(cli_env):
    result = runner.invoke(app, ["outreach", "missing"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_linkedin_message_prints(cli_env):
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["linkedin-message", job.id, "--type", "connect"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_headhunter_strategy_runs_without_jobs(cli_env):
    result = runner.invoke(app, ["headhunter", "strategy"])
    assert result.exit_code == 0


# ── profile / system ─────────────────────────────────────────────────────────

def test_validate_profile_passes_for_examples(cli_env):
    result = runner.invoke(app, ["validate-profile"])
    assert result.exit_code == 0
    assert "passed" in result.output.lower()


def test_setup_wizard_non_interactive_writes_qa(cli_env):
    result = runner.invoke(app, ["setup-wizard", "--non-interactive"])
    assert result.exit_code == 0
    qa_path = cli_env.profiles_dir / "master_qa_profile.json"
    assert qa_path.exists()
    assert "Setup wizard complete" in result.output


def test_france_setup_prints_instructions(cli_env):
    result = runner.invoke(app, ["france-setup"])
    assert result.exit_code == 0
    assert "France Travail" in result.output


def test_france_targets_lists_companies(cli_env):
    result = runner.invoke(app, ["france-targets", "--limit", "5"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_france_search_urls_json_format(cli_env):
    result = runner.invoke(app, ["france-search-urls", "--query", "data", "--single-query", "--format", "json"])
    assert result.exit_code == 0
    assert "http" in result.output


def test_export_internships_runs(cli_env):
    result = runner.invoke(app, ["export", "internships"])
    assert result.exit_code == 0
    assert "export" in result.output.lower()
