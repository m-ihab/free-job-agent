from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path

import pytest

from job_agent.db.database import Database
from job_agent.knowledge_graph import build_knowledge_graph
from job_agent.schemas.job import JobListing


@pytest.fixture
def graph_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    server_ready: Callable[[str, int], None],
) -> Iterator[tuple[int, Database]]:
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    from job_agent.ui.server import JobAgentHandler, JobAgentServer
    from job_agent.ui.services import configured_app

    config = configured_app()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    httpd = JobAgentServer(("127.0.0.1", 0), JobAgentHandler, config)
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


def _seed_graph(db: Database) -> tuple[JobListing, JobListing]:
    analyst = JobListing(
        id="job-analyst",
        title="Data Analyst",
        company="Acme",
        description="Build reporting for business teams.",
        requirements=["Python", "SQL"],
        tech_stack=["Python", "SQL"],
        fit_score=82,
    )
    engineer = JobListing(
        id="job-engineer",
        title="ML Engineer",
        company="Acme",
        description="Train and ship machine-learning systems.",
        requirements=["Python", "PyTorch"],
        tech_stack=["Python", "PyTorch"],
        fit_score=74,
    )
    db.save_job(analyst)
    db.save_job(engineer)
    db.replace_evidence_items(
        [
            {
                "kind": "skill",
                "label": "Python",
                "value": "3 years",
                "source": "profile",
                "source_ref": "candidate_profile.skills",
            },
            {
                "kind": "project",
                "label": "Forecasting pipeline",
                "value": "Built a Python and SQL forecasting pipeline",
                "source": "cv",
                "source_ref": "master_cv.projects[0]",
            },
            {
                "kind": "certification",
                "label": "Cloud fundamentals",
                "value": "Vendor-neutral certificate",
                "source": "cv",
                "source_ref": "master_cv.certifications[0]",
            },
        ]
    )
    return analyst, engineer


def _get_json(port: int, path: str) -> tuple[int, dict]:
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as conn:
        conn.request("GET", path)
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
    return response.status, payload


def test_get_graph_returns_real_jobs_skills_companies_and_evidence(
    graph_server: tuple[int, Database],
) -> None:
    port, db = graph_server
    analyst, engineer = _seed_graph(db)

    status, payload = _get_json(port, "/api/graph")

    assert status == 200
    assert payload["truncated"] is False
    assert payload["total_nodes"] == 9
    assert payload["total_edges"] == 9
    assert {node["type"] for node in payload["nodes"]} == {"skill", "job", "company", "evidence"}
    assert {edge["type"] for edge in payload["edges"]} == {"requires", "proves", "at"}
    assert all(edge["source"] != edge["target"] for edge in payload["edges"])

    nodes = {node["id"]: node for node in payload["nodes"]}
    analyst_node = nodes[f"job:{analyst.id}"]
    assert analyst_node["meta"]["fit_score"] == 82
    assert isinstance(analyst_node["meta"]["search_quality_score"], int | float)
    assert analyst_node["meta"]["company"] == "Acme"
    assert nodes[f"job:{engineer.id}"]["label"] == "ML Engineer"

    python = next(node for node in payload["nodes"] if node["type"] == "skill" and node["label"] == "Python")
    python_requires = [edge for edge in payload["edges"] if edge["type"] == "requires" and edge["target"] == python["id"]]
    python_proofs = [edge for edge in payload["edges"] if edge["type"] == "proves" and edge["target"] == python["id"]]
    assert len(python_requires) == 2
    assert len(python_proofs) == 2
    assert python["meta"]["job_count"] == 2
    assert python["meta"]["evidence_count"] == 2
    assert python["meta"]["claim_count"] == 1

    isolated = next(node for node in payload["nodes"] if node["label"] == "Cloud fundamentals")
    assert isolated["meta"]["position_source"] == "stable_seed_no_relations"
    assert isinstance(isolated["meta"]["stable_seed"], int)


def test_graph_is_honestly_empty_for_a_fresh_database(graph_server: tuple[int, Database]) -> None:
    port, _ = graph_server

    status, payload = _get_json(port, "/api/graph")

    assert status == 200
    assert payload == {
        "nodes": [], "edges": [], "truncated": False, "total_nodes": 0, "total_edges": 0,
    }


def test_graph_cap_keeps_only_edges_whose_endpoints_survive(tmp_db: Database) -> None:
    _seed_graph(tmp_db)

    payload = build_knowledge_graph(tmp_db, max_nodes=5)

    assert payload["truncated"] is True
    assert len(payload["nodes"]) == 5
    kept = {node["id"] for node in payload["nodes"]}
    assert all(edge["source"] in kept and edge["target"] in kept for edge in payload["edges"])
    assert payload["total_nodes"] == 9
    assert payload["total_edges"] == 9
