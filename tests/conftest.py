import getpass
import os
import tempfile
from pathlib import Path

import json

import pytest


def _ensure_accessible_pytest_temproot() -> None:
    """Redirect pytest's temp root if the default one is inaccessible.

    On Windows the shared ``%TEMP%\\pytest-of-<user>`` directory can become
    OS-locked (WinError 5) after a crashed run, which makes every test that uses
    the ``tmp_path``/``tmp_path_factory`` fixtures error out at setup. When the
    default root cannot be scanned, fall back to a clean project-local directory
    via ``PYTEST_DEBUG_TEMPROOT`` so the suite stays runnable everywhere.
    """
    if os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        return
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - extremely rare on locked-down hosts
        user = "unknown"
    default_root = Path(tempfile.gettempdir()) / f"pytest-of-{user}"
    if not default_root.exists():
        return  # pytest will create a fresh one; nothing to work around.
    try:
        os.scandir(default_root).close()
    except (PermissionError, OSError):
        fallback = Path(__file__).resolve().parent.parent / ".pytest_tmp"
        fallback.mkdir(parents=True, exist_ok=True)
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(fallback)


_ensure_accessible_pytest_temproot()

from job_agent.schemas.candidate import CandidateProfile, MasterCV, QAProfile  # noqa: E402  (after the temp-root workaround above)
from job_agent.schemas.job import JobListing  # noqa: E402
from job_agent.db.database import Database  # noqa: E402

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
