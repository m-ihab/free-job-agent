"""End-to-end packet-generation safety tests."""
from pathlib import Path
import shutil


from job_agent.config import AppConfig
from job_agent.db import Database
from job_agent.generator.cover_letter import generate_cover_letter
from job_agent.generator.qa import standard_locked_answers
from job_agent.pipeline import generate_packet_for_job
from job_agent.schemas.job import JobListing
from job_agent.tracker import ApplicationTracker

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _copy_profiles(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / ".job_agent"
    profiles_dir = data_dir / "profiles"
    outputs_dir = data_dir / "outputs"
    profiles_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        shutil.copyfile(EXAMPLES_DIR / name, profiles_dir / name)
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir, outputs_dir=outputs_dir, db_path=data_dir / "jobs.db")


def test_packet_generation_writes_all_promised_files(tmp_path):
    config = _copy_profiles(tmp_path)
    config.cover_letter_auto_threshold = 0
    db = Database(config.db_path)
    db.initialize()
    tracker = ApplicationTracker(db)
    job = JobListing(
        title="Senior Python Engineer",
        company="Example Analytics",
        location="San Francisco, CA",
        remote=True,
        raw_text="Senior Python Engineer\nRequirements:\n- Python\n- FastAPI\n- PostgreSQL\n- Docker",
        description="Build APIs and data systems.",
        requirements=["Python", "FastAPI", "PostgreSQL", "Docker"],
        tech_stack=["python", "fastapi", "postgresql", "docker"],
        apply_url="https://example.com/apply",
    )
    from job_agent.fingerprint import set_fingerprint
    tracker.add_job(set_fingerprint(job))
    packet = generate_packet_for_job(config, job.id)
    expected_names = {
        "cv.md",
        "cv.tex",
        "cv.html",
        "cv.pdf",
        "cover_letter.md",
        "cover_letter.html",
        "cover_letter.pdf",
        "assistant.html",
        "preflight.json",
        "proof_pack.md",
    }
    actual_names = {Path(a.path).name for a in packet.artifacts}
    assert expected_names.issubset(actual_names)
    for artifact in packet.artifacts:
        assert Path(artifact.path).exists()
        assert len(artifact.sha256) == 64
    assistant = Path(next(a.path for a in packet.artifacts if a.kind == "assistant_html")).read_text(encoding="utf-8")
    assert "Locked Screening Answers" in assistant
    assert "Do not require visa sponsorship" in assistant or "visa sponsorship" in assistant
    preflight = Path(next(a.path for a in packet.artifacts if a.kind == "preflight_json")).read_text(encoding="utf-8")
    assert '"verdict"' in preflight
    proof = Path(next(a.path for a in packet.artifacts if a.kind == "proof_pack_markdown")).read_text(encoding="utf-8")
    assert "# Proof Pack" in proof


def test_packet_includes_evaluation_and_story_bank(tmp_path):
    config = _copy_profiles(tmp_path)
    config.cover_letter_auto_threshold = 0
    db = Database(config.db_path)
    db.initialize()
    tracker = ApplicationTracker(db)
    job = JobListing(
        title="Senior Python Engineer",
        company="Example Analytics",
        location="San Francisco, CA",
        remote=True,
        raw_text="Senior Python Engineer\nRequirements:\n- Python\n- FastAPI",
        description="Build APIs and data systems.",
        requirements=["Python", "FastAPI"],
        tech_stack=["python", "fastapi"],
        apply_url="https://example.com/apply",
    )
    from job_agent.fingerprint import set_fingerprint
    tracker.add_job(set_fingerprint(job))
    packet = generate_packet_for_job(config, job.id)

    names = {Path(a.path).name for a in packet.artifacts}
    assert "evaluation.md" in names
    assert "evaluation.json" in names
    evaluation_md = Path(next(a.path for a in packet.artifacts if a.kind == "evaluation_markdown")).read_text(encoding="utf-8")
    assert "# Job evaluation" in evaluation_md
    assert "Overall" in evaluation_md
    assert "Salary context" in evaluation_md
    evaluation_json = Path(next(a.path for a in packet.artifacts if a.kind == "evaluation_json")).read_text(encoding="utf-8")
    assert '"overall_grade"' in evaluation_json

    interview = Path(next(a.path for a in packet.artifacts if Path(a.path).name == "interview_prep.md")).read_text(encoding="utf-8")
    assert "Interview story bank" in interview
    # Seeding happened as a side effect and is persistent + idempotent.
    assert db.list_stories()


def test_cover_letter_does_not_infer_sponsorship(sample_job, sample_master_cv, sample_profile):
    letter = generate_cover_letter(sample_job, sample_master_cv, sample_profile).lower()
    assert "do not require visa sponsorship" not in letter
    assert "sponsorship" not in letter


def test_standard_locked_answers_uses_qa_profile(sample_qa_profile):
    answers = standard_locked_answers(sample_qa_profile)
    assert any("visa" in key.lower() or "sponsorship" in key.lower() for key in answers)
    assert all(value for value in answers.values())
