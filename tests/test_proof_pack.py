"""Evidence-backed proof-pack generation."""
from __future__ import annotations

import shutil
from pathlib import Path

from job_agent.config import AppConfig
from job_agent.evidence import EvidenceStore
from job_agent.generator.preflight import run_preflight
from job_agent.generator.proof_pack import render_proof_pack_markdown
from job_agent.schemas.job import JobListing
from job_agent.validators import load_profile_bundle


def _config(tmp_path: Path) -> AppConfig:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        shutil.copyfile(Path("examples") / name, profiles / name)
    return AppConfig(data_dir=tmp_path / ".job_agent", db_path=tmp_path / ".job_agent" / "jobs.db", profiles_dir=profiles)


def test_proof_pack_markdown_is_grounded_in_preflight_evidence(tmp_path):
    config = _config(tmp_path)
    profile, _master, _qa = load_profile_bundle(config)
    evidence = EvidenceStore.load(config)
    evidence.rebuild(config)
    job = JobListing(
        title="Data Scientist Intern",
        company="ACME",
        requirements=["Python", "SQL", "Kubernetes"],
        description="Work with Python, SQL, and Kubernetes.",
        tech_stack=["Python", "SQL", "Kubernetes"],
    )
    preflight = run_preflight(job, profile, evidence, config)

    markdown = render_proof_pack_markdown(job, preflight)

    assert "# Proof Pack" in markdown
    assert "Python" in markdown
    assert "Unsupported claims to avoid" in markdown
    assert "Kubernetes" in markdown
    assert "42%" not in markdown
