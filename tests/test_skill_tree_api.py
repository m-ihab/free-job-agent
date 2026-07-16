from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path

import pytest

from job_agent.db.database import Database
from job_agent.schemas.candidate import (
    CandidateProfile,
    ContactInfo,
    MasterCV,
    Project,
    QAProfile,
    Skill,
)
from job_agent.schemas.job import JobListing


def _write_profile_bundle(profiles_dir: Path, *, seeded: bool) -> None:
    contact = ContactInfo(name="Synthetic Candidate", email="synthetic@example.test")
    skills = [Skill(name="Python"), Skill(name="SQL"), Skill(name="Docker")] if seeded else []
    profile = CandidateProfile(
        contact=contact,
        skills=skills,
        target_roles=["Data Scientist"] if seeded else [],
    )
    projects = (
        [
            Project(
                name="Synthetic model service",
                description="Built a tested model service.",
                technologies=["Python", "Docker"],
            )
        ]
        if seeded
        else []
    )
    master_cv = MasterCV(contact=contact, skills=skills, projects=projects)
    (profiles_dir / "candidate_profile.json").write_text(profile.json(), encoding="utf-8")
    (profiles_dir / "master_cv.json").write_text(master_cv.json(), encoding="utf-8")
    (profiles_dir / "master_qa_profile.json").write_text(QAProfile().json(), encoding="utf-8")


def _serve_skill_tree(
    seeded: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    server_ready: Callable[[str, int], None],
) -> Iterator[tuple[int, Database]]:
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True)
    _write_profile_bundle(profiles_dir, seeded=seeded)
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(profiles_dir))

    db = Database(data_dir / "jobs.db")
    db.initialize()
    if seeded:
        db.save_job(
            JobListing(
                id="skill-tree-job",
                title="Data Scientist",
                company="Synthetic Co",
                description="Build and deploy models.",
                requirements=["Python", "SQL", "Docker", "DevOps", "AWS"],
                tech_stack=["Python", "SQL", "Docker", "DevOps", "AWS"],
                fit_score=45,
            )
        )

    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, configured_app())
    port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    server_ready("127.0.0.1", port)
    try:
        yield port, db
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def fresh_skill_tree_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    server_ready: Callable[[str, int], None],
) -> Iterator[tuple[int, Database]]:
    yield from _serve_skill_tree(False, monkeypatch, tmp_path, server_ready)


@pytest.fixture
def skill_tree_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    server_ready: Callable[[str, int], None],
) -> Iterator[tuple[int, Database]]:
    yield from _serve_skill_tree(True, monkeypatch, tmp_path, server_ready)


def _get_json(port: int, path: str) -> tuple[int, dict[str, object]]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", path)
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
    return response.status, payload


def test_skill_tree_is_honestly_empty_without_profile_skills_or_jobs(
    fresh_skill_tree_server: tuple[int, Database],
) -> None:
    port, _db = fresh_skill_tree_server

    status, payload = _get_json(port, "/api/skill-tree")

    assert status == 200
    assert payload == {"skills": [], "roles": []}


def test_skill_tree_returns_evidence_claim_gap_edges_and_role_readiness(
    skill_tree_server: tuple[int, Database],
) -> None:
    port, _db = skill_tree_server

    status, payload = _get_json(port, "/api/skill-tree")

    assert status == 200
    skills = {row["label"]: row for row in payload["skills"]}
    assert set(skills) == {"AWS", "DevOps", "Docker", "Python", "SQL"}
    assert {name: row["state"] for name, row in skills.items()} == {
        "AWS": "locked",
        "DevOps": "locked",
        "Docker": "unlocked",
        "Python": "unlocked",
        "SQL": "claimed",
    }
    assert skills["Python"]["evidenceCount"] == 1
    assert skills["SQL"]["evidenceCount"] == 0
    assert skills["DevOps"]["jobsRequiring"] == 1
    assert skills["DevOps"]["unlock"]["jobsBlocked"] == 1
    assert skills["Docker"]["id"] in skills["DevOps"]["parents"]
    assert skills["AWS"]["scoreLift"] >= 0
    assert skills["AWS"]["unlock"]["certs"]
    assert skills["AWS"]["unlock"]["projects"]
    assert "url" not in json.dumps(payload).casefold()

    assert payload["roles"] == [
        {
            "role": "Data Scientist",
            "skillIds": [skills[name]["id"] for name in sorted(skills, key=str.casefold)],
            "readiness": 40,
        }
    ]


def test_skill_tree_get_does_not_persist_rebuilt_evidence(
    skill_tree_server: tuple[int, Database],
) -> None:
    port, db = skill_tree_server
    before = db.list_evidence_items()

    status, _payload = _get_json(port, "/api/skill-tree")

    assert status == 200
    assert db.list_evidence_items() == before
