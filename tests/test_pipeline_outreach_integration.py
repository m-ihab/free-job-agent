"""TDD Area 1: Pipeline integration — outreach_email.md artifact + language mismatch flag.

RED: verify the pipeline writes outreach_email.md to every packet folder and
     that its content is grounded in the candidate profile.
"""
from __future__ import annotations

import shutil
from pathlib import Path


from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.fingerprint import set_fingerprint
from job_agent.pipeline import generate_packet_for_job
from job_agent.schemas.job import JobListing
from job_agent.tracker import ApplicationTracker

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _config(tmp_path: Path, languages: list[str] | None = None) -> AppConfig:
    import json as _json
    data_dir = tmp_path / ".job_agent"
    profiles_dir = data_dir / "profiles"
    outputs_dir = data_dir / "outputs"
    profiles_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        shutil.copyfile(EXAMPLES_DIR / name, profiles_dir / name)
    if languages is not None:
        profile_path = profiles_dir / "candidate_profile.json"
        profile = _json.loads(profile_path.read_text(encoding="utf-8"))
        profile["languages"] = languages
        profile_path.write_text(_json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    db_path = data_dir / "jobs.db"
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir, outputs_dir=outputs_dir, db_path=db_path)


def _add_job(config: AppConfig, **kwargs) -> JobListing:
    db = Database(config.db_path)
    db.initialize()
    tracker = ApplicationTracker(db)
    defaults = dict(
        title="Data Scientist",
        company="Acme Labs",
        location="Paris, France",
        raw_text="Data Scientist. Python, pandas, scikit-learn.",
        tech_stack=["python", "pandas", "scikit-learn"],
        apply_url="https://acme.io/apply",
    )
    defaults.update(kwargs)
    job = set_fingerprint(JobListing(**defaults))
    tracker.add_job(job)
    return job


# ── Outreach email artifact ────────────────────────────────────────────────────

class TestOutreachEmailArtifact:
    def test_packet_includes_outreach_email_artifact(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        job = _add_job(config)
        packet = generate_packet_for_job(config, job.id)
        artifact_names = {Path(a.path).name for a in packet.artifacts}
        assert "outreach_email.md" in artifact_names, \
            "packet artifacts should include outreach_email.md"

    def test_outreach_email_file_exists_on_disk(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        job = _add_job(config)
        packet = generate_packet_for_job(config, job.id)
        outreach_artifact = next(
            (a for a in packet.artifacts if Path(a.path).name == "outreach_email.md"),
            None,
        )
        assert outreach_artifact is not None
        assert Path(outreach_artifact.path).exists()

    def test_outreach_email_contains_job_title(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        job = _add_job(config, title="ML Platform Engineer")
        packet = generate_packet_for_job(config, job.id)
        outreach_artifact = next(a for a in packet.artifacts if Path(a.path).name == "outreach_email.md")
        content = Path(outreach_artifact.path).read_text(encoding="utf-8")
        assert "ML Platform Engineer" in content

    def test_outreach_email_contains_subject_line(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        job = _add_job(config)
        packet = generate_packet_for_job(config, job.id)
        outreach_artifact = next(a for a in packet.artifacts if Path(a.path).name == "outreach_email.md")
        content = Path(outreach_artifact.path).read_text(encoding="utf-8")
        assert "Subject" in content

    def test_outreach_email_not_empty(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        job = _add_job(config)
        packet = generate_packet_for_job(config, job.id)
        outreach_artifact = next(a for a in packet.artifacts if Path(a.path).name == "outreach_email.md")
        content = Path(outreach_artifact.path).read_text(encoding="utf-8")
        assert len(content.split()) >= 20, "outreach email should have at least 20 words"

    def test_outreach_email_uses_recruiter_name_when_present(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        job = _add_job(
            config,
            raw_text="Data Scientist. Python required.\nRecruiter: Sophie Martin",
            recruiter_name="Sophie Martin",
        )
        packet = generate_packet_for_job(config, job.id)
        outreach_artifact = next(a for a in packet.artifacts if Path(a.path).name == "outreach_email.md")
        content = Path(outreach_artifact.path).read_text(encoding="utf-8")
        assert "Sophie Martin" in content

    def test_all_packet_artifacts_have_valid_sha256(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        job = _add_job(config)
        packet = generate_packet_for_job(config, job.id)
        for artifact in packet.artifacts:
            assert len(artifact.sha256) == 64, \
                f"artifact {artifact.kind} has invalid sha256: {artifact.sha256!r}"


# ── Language mismatch flag ─────────────────────────────────────────────────────

class TestLanguageMismatchFlag:
    def test_flag_added_when_french_required_and_not_in_profile(self, tmp_path: Path) -> None:
        config = _config(tmp_path, languages=["English"])  # English-only candidate
        job = _add_job(
            config,
            languages=["French"],
            raw_text="Data Scientist à Paris. Français courant requis. Python, pandas.",
        )
        # The example candidate_profile.json is English-only
        generate_packet_for_job(config, job.id)
        updated_db = Database(config.db_path)
        updated_db.initialize()
        updated_job = ApplicationTracker(updated_db).get_job(job.id)
        assert "LANGUAGE_MISMATCH" in (updated_job.risk_flags or []), \
            "LANGUAGE_MISMATCH should be set when job requires French but candidate doesn't speak it"

    def test_flag_not_added_for_english_only_job(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        job = _add_job(
            config,
            languages=["English"],
            raw_text="Data Scientist. English fluency required. Python, pandas.",
        )
        generate_packet_for_job(config, job.id)
        updated_db = Database(config.db_path)
        updated_db.initialize()
        updated_job = ApplicationTracker(updated_db).get_job(job.id)
        assert "LANGUAGE_MISMATCH" not in (updated_job.risk_flags or [])

    def test_flag_not_added_when_no_language_requirement(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        job = _add_job(config)
        generate_packet_for_job(config, job.id)
        updated_db = Database(config.db_path)
        updated_db.initialize()
        updated_job = ApplicationTracker(updated_db).get_job(job.id)
        assert "LANGUAGE_MISMATCH" not in (updated_job.risk_flags or [])
