"""Round-2 behavioural tests for CLI command handlers — remaining branches.

Covers the uncovered branches in search/profile/outreach/apply/france/_common
command modules: error paths, save flows, multi-source, smart-plan, enrichment,
import-cv-template, audit/suggest-skills, interview-prep/followup/headhunter, and
the France hunt/search-url variants. Every network/LLM/browser call is mocked and
all app directories are redirected to a temp path.
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

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
runner = CliRunner()


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch):
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


def _api_job(title="Data Scientist", url="https://example.com/1") -> JobListing:
    return JobListing(title=title, company="Acme", source="api:remotive",
                      raw_text="x", apply_url=url, description="Python ML role.")


# ── search-api: table render + full URLs + save dedupe ───────────────────────

def test_search_api_renders_results_and_full_urls(cli_env, monkeypatch):
    from job_agent.cli import main
    monkeypatch.setattr(main, "search_free_api_jobs", lambda *a, **k: [_api_job()])
    result = runner.invoke(app, ["search-api", "remotive", "--query", "data"])
    assert result.exit_code == 0
    assert "Data Scientist" in result.output
    assert "https://example.com/1" in result.output


def test_search_api_save_counts_duplicates(cli_env, monkeypatch):
    from job_agent.cli import main
    job = _api_job(url="https://example.com/dup")
    monkeypatch.setattr(main, "search_free_api_jobs", lambda *a, **k: [job, job])
    result = runner.invoke(app, ["search-api", "remotive", "--query", "data", "--save"])
    assert result.exit_code == 0
    assert "Saved 1 new jobs (1 duplicates skipped)." in result.output


def test_search_api_generic_error_branch(cli_env, monkeypatch):
    from job_agent.cli import main

    def _boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(main, "search_free_api_jobs", _boom)
    result = runner.invoke(app, ["search-api", "remotive"])
    assert result.exit_code != 0
    assert "Failed to search source" in result.output


# ── hunt: no-profile guard, prepare packets, and failure capture ─────────────

def test_hunt_without_profile_fails(cli_env, monkeypatch):
    # Remove profile files so load_profile_bundle returns None.
    for name in ("candidate_profile.json", "master_cv.json", "master_qa_profile.json"):
        (cli_env.profiles_dir / name).unlink()
    result = runner.invoke(app, ["hunt", "remotive", "--query", "data"])
    assert result.exit_code != 0
    assert "Cannot hunt without valid profile" in result.output


def test_hunt_prepares_packets_and_reports(cli_env, monkeypatch):
    from job_agent.cli import main
    from job_agent.cli.commands import search as search_cmds
    monkeypatch.setattr(main, "search_free_api_jobs", lambda *a, **k: [_api_job(url="https://example.com/hunt1")])
    monkeypatch.setattr(search_cmds, "generate_packet_for_job", lambda *a, **k: object())
    result = runner.invoke(app, ["hunt", "remotive", "--query", "data"])
    assert result.exit_code == 0
    assert "Imported and prepared packets: 1" in result.output


def test_hunt_records_packet_failures(cli_env, monkeypatch):
    from job_agent.cli import main
    from job_agent.cli.commands import search as search_cmds
    monkeypatch.setattr(main, "search_free_api_jobs", lambda *a, **k: [_api_job(url="https://example.com/huntfail")])

    def _boom(*a, **k):
        raise RuntimeError("latex failed")
    monkeypatch.setattr(search_cmds, "generate_packet_for_job", _boom)
    result = runner.invoke(app, ["hunt", "remotive", "--query", "data"])
    assert result.exit_code == 0
    assert "Failures: 1" in result.output
    assert "Skipped:" in result.output


def test_hunt_no_results_reports_empty(cli_env, monkeypatch):
    from job_agent.cli import main
    monkeypatch.setattr(main, "search_free_api_jobs", lambda *a, **k: [])
    result = runner.invoke(app, ["hunt", "remotive", "--query", "data"])
    assert result.exit_code == 0
    assert "No jobs found." in result.output


# ── multi-search ─────────────────────────────────────────────────────────────

def test_multi_search_renders_and_saves(cli_env, monkeypatch):
    from job_agent.cli import main
    job = _api_job(url="https://example.com/multi1")
    monkeypatch.setattr(main, "search_all_free_sources", lambda **k: {
        "jobs": [job],
        "per_source": {"remotive": 1},
        "errors": {},
    })
    # search.py imports search_all_free_sources directly into its namespace.
    from job_agent.cli.commands import search as search_cmds
    monkeypatch.setattr(search_cmds, "search_all_free_sources", lambda **k: {
        "jobs": [job],
        "per_source": {"remotive": 1},
        "errors": {},
    })
    result = runner.invoke(app, ["multi-search", "--query", "data", "--sources", "remotive", "--save"])
    assert result.exit_code == 0
    assert "remotive: 1" in result.output
    assert "Saved 1 new jobs" in result.output


def test_multi_search_reports_source_errors(cli_env, monkeypatch):
    from job_agent.cli.commands import search as search_cmds
    monkeypatch.setattr(search_cmds, "search_all_free_sources", lambda **k: {
        "jobs": [],
        "per_source": {},
        "errors": {"remotive": "boom"},
    })
    result = runner.invoke(app, ["multi-search", "--query", "data"])
    assert result.exit_code == 0
    assert "Errors:" in result.output


# ── smart-plan ───────────────────────────────────────────────────────────────

def test_smart_plan_prints_queries(cli_env, monkeypatch):
    from job_agent.cli.commands import search as search_cmds
    monkeypatch.setattr(search_cmds, "suggest_search_queries", lambda *a, **k: {
        "used_ai": False,
        "model": None,
        "rationale": "deterministic expansion",
        "queries": ["data scientist stage", "ml engineer intern"],
    })
    result = runner.invoke(app, ["smart-plan", "--query", "data"])
    assert result.exit_code == 0
    assert "1. data scientist stage" in result.output
    assert "deterministic" in result.output


# ── add rss / discover-links (network mocked) ────────────────────────────────

def test_add_rss_imports_jobs(cli_env, monkeypatch):
    from job_agent.cli.commands import search as search_cmds
    rss_job = JobListing(title="RSS Role", company="[To Be Parsed]", source="rss",
                         raw_text="RSS Role body", apply_url="https://example.com/rss1")
    monkeypatch.setattr(search_cmds, "ingest_rss", lambda *a, **k: [rss_job])
    result = runner.invoke(app, ["add", "rss", "https://feed.example.com/jobs.xml"])
    assert result.exit_code == 0
    assert "Imported 1/1 new jobs from RSS feed." in result.output


def test_discover_links_prints_links(cli_env, monkeypatch):
    from job_agent.cli.commands import search as search_cmds
    monkeypatch.setattr(search_cmds, "discover_job_links", lambda *a, **k: ["https://x/careers/1"])
    result = runner.invoke(app, ["discover-links", "https://x.example.com"])
    assert result.exit_code == 0
    assert "https://x/careers/1" in result.output


def test_discover_links_none_found(cli_env, monkeypatch):
    from job_agent.cli.commands import search as search_cmds
    monkeypatch.setattr(search_cmds, "discover_job_links", lambda *a, **k: [])
    result = runner.invoke(app, ["discover-links", "https://x.example.com"])
    assert result.exit_code == 0
    assert "No likely job links found." in result.output


def test_discover_links_error_branch(cli_env, monkeypatch):
    from job_agent.cli.commands import search as search_cmds

    def _boom(*a, **k):
        raise RuntimeError("fetch failed")
    monkeypatch.setattr(search_cmds, "discover_job_links", _boom)
    result = runner.invoke(app, ["discover-links", "https://x.example.com"])
    assert result.exit_code != 0
    assert "Failed to discover links" in result.output


# ── profile: enrich-github / enrich-linkedin / import-cv-template ────────────

def test_enrich_github_success(cli_env, monkeypatch):
    from job_agent.cli.commands import profile as profile_cmds
    monkeypatch.setattr(profile_cmds, "enrich_from_github", lambda *a, **k: {
        "handle": "octocat",
        "public_repos": 5,
        "languages_seen": ["Python", "Go"],
        "added_skills": ["python"],
        "added_projects": ["repo1"],
        "updated_contact": True,
    })
    result = runner.invoke(app, ["enrich-github", "--handle", "octocat"])
    assert result.exit_code == 0
    assert "GitHub handle: octocat" in result.output


def test_enrich_github_requires_handle(cli_env, monkeypatch):
    # Strip github_url from the copied candidate profile so no handle resolves.
    import json
    path = cli_env.profiles_dir / "candidate_profile.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("contact", {})["github_url"] = ""
    path.write_text(json.dumps(data), encoding="utf-8")
    result = runner.invoke(app, ["enrich-github"])
    assert result.exit_code != 0
    assert "Provide --handle" in result.output


def test_enrich_github_failure_branch(cli_env, monkeypatch):
    from job_agent.cli.commands import profile as profile_cmds

    def _boom(*a, **k):
        raise RuntimeError("rate limited")
    monkeypatch.setattr(profile_cmds, "enrich_from_github", _boom)
    result = runner.invoke(app, ["enrich-github", "--handle", "octocat"])
    assert result.exit_code != 0
    assert "GitHub enrichment failed" in result.output


def test_enrich_linkedin_from_file(cli_env, monkeypatch, tmp_path):
    from job_agent.cli.commands import profile as profile_cmds
    skills_file = tmp_path / "skills.txt"
    skills_file.write_text("Python\nSQL\n", encoding="utf-8")
    monkeypatch.setattr(profile_cmds, "enrich_from_linkedin_skills", lambda *a, **k: {
        "parsed_count": 2,
        "added_skills": ["sql"],
        "candidate_path": "candidate_profile.json",
        "master_cv_path": "master_cv.json",
    })
    result = runner.invoke(app, ["enrich-linkedin", "--file", str(skills_file)])
    assert result.exit_code == 0
    assert "Parsed skills: 2" in result.output


def test_enrich_linkedin_missing_file_fails(cli_env):
    result = runner.invoke(app, ["enrich-linkedin", "--file", "no_such_file.txt"])
    assert result.exit_code != 0
    assert "Could not read" in result.output


def test_import_cv_template_missing_file_fails(cli_env):
    result = runner.invoke(app, ["import-cv-template", "missing_template.tex"])
    assert result.exit_code != 0
    assert "Template file not found" in result.output


def test_import_cv_template_imports_tex(cli_env, tmp_path):
    tex = tmp_path / "main.tex"
    tex.write_text("\\documentclass{article}\\begin{document}Hi\\end{document}", encoding="utf-8")
    result = runner.invoke(app, ["import-cv-template", str(tex)])
    assert result.exit_code == 0
    assert "CV template imported" in result.output
    assert (cli_env.profiles_dir / "main.tex").exists()


def test_import_cv_template_rejects_unsupported(cli_env, tmp_path):
    bad = tmp_path / "notes.exe"
    bad.write_bytes(b"MZ binary")
    result = runner.invoke(app, ["import-cv-template", str(bad)])
    assert result.exit_code != 0
    assert "Could not import CV template" in result.output


# ── profile: audit / suggest-skills ──────────────────────────────────────────

def test_audit_profile_writes_report(cli_env):
    result = runner.invoke(app, ["audit-profile"])
    assert result.exit_code == 0
    assert (cli_env.profiles_dir / "profile_audit_report.md").exists()


def test_suggest_skills_runs(cli_env):
    result = runner.invoke(app, ["suggest-skills"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_copy_examples_copies_then_skips(cli_env):
    # Profiles already exist (fixture copied them) -> "Exists, not overwriting".
    result = runner.invoke(app, ["copy-examples"])
    assert result.exit_code == 0
    assert "Exists, not overwriting" in result.output


def test_copy_examples_into_empty_profiles(cli_env):
    for name in ("candidate_profile.json", "master_cv.json", "master_qa_profile.json"):
        (cli_env.profiles_dir / name).unlink()
    result = runner.invoke(app, ["copy-examples"])
    assert result.exit_code == 0
    assert "Copied:" in result.output
    assert (cli_env.profiles_dir / "candidate_profile.json").exists()


def test_add_paste_then_duplicate_detected(cli_env, monkeypatch):
    # First paste adds the job; second identical paste is deduped by fingerprint.
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(
        "Data Scientist at Acme\n\nWe build ML models in Python and SQL."))
    first = runner.invoke(app, ["add", "paste", "--title", "Data Scientist", "--company", "Acme"])
    assert first.exit_code == 0
    assert "Added job" in first.output
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(
        "Data Scientist at Acme\n\nWe build ML models in Python and SQL."))
    second = runner.invoke(app, ["add", "paste", "--title", "Data Scientist", "--company", "Acme"])
    assert second.exit_code == 0
    assert "Duplicate detected" in second.output


def test_setup_wizard_creates_qa_entries(cli_env):
    # Remove the example QA profile so the wizard builds entries from scratch.
    (cli_env.profiles_dir / "master_qa_profile.json").unlink()
    result = runner.invoke(app, ["setup-wizard", "--non-interactive"])
    assert result.exit_code == 0
    import json
    qa = json.loads((cli_env.profiles_dir / "master_qa_profile.json").read_text(encoding="utf-8"))
    ids = {e["id"] for e in qa["entries"]}
    assert "work_authorization_france" in ids
    assert "languages_fr_en" in ids


# ── outreach: market-report / interview-prep / followup / headhunter ─────────

def test_market_report_saves_to_file(cli_env, tmp_path):
    _seed_job(cli_env)
    out = tmp_path / "market.md"
    result = runner.invoke(app, ["market-report", "--output", str(out)])
    assert result.exit_code == 0
    assert out.exists()


def test_interview_prep_prints(cli_env, monkeypatch):
    from job_agent.cli.commands import outreach as outreach_cmds
    monkeypatch.setattr(outreach_cmds, "generate_interview_prep",
                        lambda *a, **k: "# Interview prep\n- Tell me about yourself")
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["interview-prep", job.id])
    assert result.exit_code == 0
    assert "Interview prep" in result.output


def test_interview_prep_saves_to_packet_dir(cli_env, monkeypatch, tmp_path):
    from job_agent.cli.commands import outreach as outreach_cmds
    monkeypatch.setattr(outreach_cmds, "generate_interview_prep", lambda *a, **k: "prep body")
    job = _seed_job(cli_env)
    db = Database(cli_env.db_path)
    packet_dir = tmp_path / "packet_out"
    packet_dir.mkdir()
    cv_path = packet_dir / "cv.pdf"
    cv_path.write_text("x", encoding="utf-8")
    packet = ApplicationPacket(id="pkt_iv", job_id=job.id, status=PacketStatus.READY,
                               tailored_cv_pdf_path=str(cv_path))
    db.save_packet(packet)
    result = runner.invoke(app, ["interview-prep", job.id, "--save"])
    assert result.exit_code == 0
    assert (packet_dir / "interview_prep.md").exists()


def test_interview_prep_unknown_job_fails(cli_env):
    result = runner.invoke(app, ["interview-prep", "missing"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_followup_email_prints(cli_env):
    job = _seed_job(cli_env)
    result = runner.invoke(app, ["followup-email", job.id, "--type", "week2"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_followup_email_unknown_job_fails(cli_env):
    result = runner.invoke(app, ["followup-email", "missing"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_linkedin_message_connect_and_followup(cli_env):
    job = _seed_job(cli_env)
    for msg_type in ("connect", "followup"):
        result = runner.invoke(app, ["linkedin-message", job.id, "--type", msg_type])
        assert result.exit_code == 0
        assert result.output.strip()


def test_headhunter_batch_no_jobs_reports_threshold(cli_env):
    result = runner.invoke(app, ["headhunter", "batch", "--min-score", "99"])
    assert result.exit_code == 0
    assert "No jobs found with score" in result.output


def test_headhunter_batch_generates_pack(cli_env, monkeypatch, tmp_path):
    from job_agent.cli.commands import outreach as outreach_cmds
    _seed_job(cli_env, status=JobStatus.SCORED)
    monkeypatch.setattr(outreach_cmds, "build_batch_outreach", lambda *a, **k: [{"msg": "hi"}])
    monkeypatch.setattr(outreach_cmds, "write_batch_outreach_file", lambda packs, out: len(packs))
    out = tmp_path / "batch.md"
    result = runner.invoke(app, ["headhunter", "batch", "--output", str(out)])
    assert result.exit_code == 0
    assert "Generated 1 outreach packs" in result.output


def test_headhunter_strategy_saves_report(cli_env, tmp_path):
    out = tmp_path / "strategy.md"
    result = runner.invoke(app, ["headhunter", "strategy", "--output", str(out)])
    assert result.exit_code == 0
    assert out.exists()


def test_outreach_shows_recruiter_contact(cli_env):
    db = Database(cli_env.db_path)
    job = JobListing(title="Data Scientist", company="Acme", source="paste",
                     raw_text="x", description="Python role.",
                     recruiter_name="Jane Doe", recruiter_email="jane@acme.test")
    db.save_job(job)
    result = runner.invoke(app, ["outreach", job.id])
    assert result.exit_code == 0
    assert "Jane Doe" in result.output
    assert "jane@acme.test" in result.output


# ── apply: apply-assist / packet show / process file ─────────────────────────

def test_apply_assist_unknown_packet_fails(cli_env):
    result = runner.invoke(app, ["apply-assist", "missing"])
    assert result.exit_code != 0
    assert "Packet not found" in result.output


def test_apply_assist_marks_opened(cli_env):
    job = _seed_job(cli_env)
    db = Database(cli_env.db_path)
    packet = ApplicationPacket(id="pkt_assist", job_id=job.id, status=PacketStatus.READY)
    db.save_packet(packet)
    result = runner.invoke(app, ["apply-assist", packet.id, "--no-open-browser"])
    assert result.exit_code == 0
    assert db.get_packet(packet.id).status == PacketStatus.ASSISTED_APPLY_OPENED
    assert db.get_job(job.id).status == JobStatus.ASSISTED_APPLY_OPENED


def test_packet_show_resolves_by_job_id(cli_env):
    job = _seed_job(cli_env)
    db = Database(cli_env.db_path)
    packet = ApplicationPacket(id="pkt_show", job_id=job.id, status=PacketStatus.READY,
                               tailored_cv_pdf_path="cv.pdf")
    db.save_packet(packet)
    result = runner.invoke(app, ["packet", "show", job.id])
    assert result.exit_code == 0
    assert "pkt_show" in result.output


def test_process_file_reports_success(cli_env, monkeypatch, tmp_path):
    from job_agent.cli.commands import apply as apply_cmds
    job = JobListing(title="Parsed Role", company="Acme", source="file", raw_text="x")
    packet = ApplicationPacket(id="pkt_proc", job_id=job.id, status=PacketStatus.READY, fit_score=72.0)
    monkeypatch.setattr(apply_cmds, "process_file", lambda *a, **k: (job, packet, True))
    jd = tmp_path / "jd.txt"
    jd.write_text("Data scientist role", encoding="utf-8")
    result = runner.invoke(app, ["process", "file", str(jd)])
    assert result.exit_code == 0
    assert "score=72.0/100" in result.output


def test_process_file_reports_duplicate(cli_env, monkeypatch, tmp_path):
    from job_agent.cli.commands import apply as apply_cmds
    job = JobListing(title="Dup Role", company="Acme", source="file", raw_text="x")
    monkeypatch.setattr(apply_cmds, "process_file", lambda *a, **k: (job, None, False))
    jd = tmp_path / "jd.txt"
    jd.write_text("dup", encoding="utf-8")
    result = runner.invoke(app, ["process", "file", str(jd)])
    assert result.exit_code == 0
    assert "Duplicate detected" in result.output


def test_process_file_error_branch(cli_env, monkeypatch, tmp_path):
    from job_agent.cli.commands import apply as apply_cmds

    def _boom(*a, **k):
        raise RuntimeError("parse failed")
    monkeypatch.setattr(apply_cmds, "process_file", _boom)
    jd = tmp_path / "jd.txt"
    jd.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["process", "file", str(jd)])
    assert result.exit_code != 0
    assert "Processing failed" in result.output


# ── france: search-urls table/list formats, targets, hunt ────────────────────

def test_france_search_urls_list_format_expands(cli_env):
    result = runner.invoke(app, ["france-search-urls", "--query", "data", "--format", "list"])
    assert result.exit_code == 0
    assert "http" in result.output
    assert "Expanded queries:" in result.output


def test_france_search_urls_table_and_output_file(cli_env, tmp_path):
    out = tmp_path / "urls.txt"
    result = runner.invoke(app, ["france-search-urls", "--query", "data", "--single-query",
                                 "--format", "table", "--output", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    assert "Saved full URLs to" in result.output


def test_france_hunt_imports_via_mocked_api(cli_env, monkeypatch):
    from job_agent.cli import main
    from job_agent.cli.commands import france as france_cmds
    job = _api_job(url="https://example.com/fr1")
    monkeypatch.setattr(main, "search_free_api_jobs", lambda *a, **k: [job])
    monkeypatch.setattr(france_cmds, "generate_packet_for_job", lambda *a, **k: object())
    result = runner.invoke(app, ["france-hunt", "--query", "data scientist", "--limit-queries", "1"])
    assert result.exit_code == 0
    assert "Imported: 1" in result.output
    assert "Packets prepared: 1" in result.output


def test_france_hunt_handles_api_unavailable(cli_env, monkeypatch):
    from job_agent.cli import main
    from job_agent.intake.free_apis import FreeApiError

    def _raise(*a, **k):
        raise FreeApiError("no credentials")
    monkeypatch.setattr(main, "search_free_api_jobs", _raise)
    result = runner.invoke(app, ["france-hunt", "--query", "data", "--limit-queries", "1", "--no-packets"])
    assert result.exit_code == 0
    assert "France Travail not available" in result.output


def test_france_hunt_default_queries_when_blank(cli_env, monkeypatch):
    from job_agent.cli import main
    monkeypatch.setattr(main, "search_free_api_jobs", lambda *a, **k: [])
    result = runner.invoke(app, ["france-hunt", "--limit-queries", "2", "--no-packets"])
    assert result.exit_code == 0
    assert "France hunt complete" in result.output
