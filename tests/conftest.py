import pytest
import json
from pathlib import Path
import tempfile

from job_agent.schemas.candidate import CandidateProfile, MasterCV, QAProfile
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.db.database import Database

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.fixture
def sample_job():
    return JobListing(
        title="Senior Python Engineer",
        company="TechCorp Inc.",
        location="San Francisco, CA",
        remote=True,
        description="We are looking for a senior Python engineer to join our team.",
        requirements=["5+ years Python", "Experience with FastAPI", "PostgreSQL knowledge"],
        responsibilities=["Build scalable APIs", "Mentor junior engineers"],
        tech_stack=["python", "fastapi", "postgresql", "docker"],
        apply_url="https://example.com/apply",
        source="paste",
        raw_text="Senior Python Engineer at TechCorp Inc.\n\nWe are looking for a senior Python engineer...",
    )


@pytest.fixture
def sample_profile():
    with open(EXAMPLES_DIR / "candidate_profile.json") as f:
        data = json.load(f)
    return CandidateProfile(**data)


@pytest.fixture
def sample_master_cv():
    with open(EXAMPLES_DIR / "master_cv.json") as f:
        data = json.load(f)
    return MasterCV(**data)


@pytest.fixture
def sample_qa_profile():
    with open(EXAMPLES_DIR / "master_qa_profile.json") as f:
        data = json.load(f)
    return QAProfile(**data)


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        db.initialize()
        yield db
