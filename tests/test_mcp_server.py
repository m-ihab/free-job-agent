"""Hermetic tests for the stdlib MCP stdio facade."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from job_agent.mcp_server import handle_line, handle_request

ROOT = Path(__file__).parent.parent
EXAMPLES_DIR = ROOT / "examples"
PROFILE_FILES = ("candidate_profile.json", "master_cv.json", "master_qa_profile.json")

JOB_TEXT = """Data Scientist Intern
Location: Paris, France
Remote role with a salary of $45,000 - $55,000 per year.

Requirements:
- Python
- SQL
- Docker
- Machine learning
"""


@pytest.fixture(autouse=True)
def isolated_profiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Pin profile discovery to tracked examples, never an owner's local files."""
    data_dir = tmp_path / "data"
    profiles_dir = data_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    for name in PROFILE_FILES:
        shutil.copy(EXAMPLES_DIR / name, profiles_dir / name)
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(profiles_dir))
    return profiles_dir


def _request(method: str, params: dict[str, object] | None = None, request_id: int = 1) -> dict[str, object]:
    request: dict[str, object] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        request["params"] = params
    return request


def _tool_call(name: str, arguments: dict[str, object]) -> dict[str, object]:
    response = handle_request(_request("tools/call", {"name": name, "arguments": arguments}))
    assert response is not None
    return response


def _tool_payload(response: dict[str, object]) -> dict[str, object]:
    result = response["result"]
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, list)
    item = content[0]
    assert isinstance(item, dict)
    return json.loads(str(item["text"]))


def test_initialize_handshake() -> None:
    response = handle_request(
        _request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1"},
            },
        )
    )

    assert response is not None
    assert response["jsonrpc"] == "2.0"
    result = response["result"]
    assert isinstance(result, dict)
    assert result["protocolVersion"] == "2025-11-25"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"] == {"name": "free-job-agent", "version": "0.3.0"}


def test_initialized_notification_is_ignored() -> None:
    assert handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_has_exactly_three_read_only_tools() -> None:
    response = handle_request(_request("tools/list"))

    assert response is not None
    result = response["result"]
    assert isinstance(result, dict)
    tools = result["tools"]
    assert isinstance(tools, list)
    assert {tool["name"] for tool in tools} == {
        "score_job_fit",
        "extract_job_intel",
        "evaluate_job_quality",
    }
    assert len(tools) == 3
    for tool in tools:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["annotations"]["readOnlyHint"] is True


def test_score_job_fit_returns_deterministic_breakdown() -> None:
    response = _tool_call(
        "score_job_fit",
        {"job_text": JOB_TEXT, "title": "Data Scientist Intern", "company": "ACME", "location": "Paris"},
    )

    result = response["result"]
    assert isinstance(result, dict)
    assert result["isError"] is False
    payload = _tool_payload(response)
    assert 0 <= int(payload["total_score"]) <= 100
    components = payload["components"]
    assert isinstance(components, list)
    assert {component["name"] for component in components} == {
        "skill", "title", "location", "seniority", "language", "salary",
    }


def test_extract_job_intel_returns_normalized_and_implied_skills() -> None:
    response = _tool_call("extract_job_intel", {"job_text": JOB_TEXT})

    result = response["result"]
    assert isinstance(result, dict)
    assert result["isError"] is False
    payload = _tool_payload(response)
    assert {"python", "sql", "docker"}.issubset(set(payload["tech_stack"]))
    assert payload["salary_min"] == 45000
    assert payload["salary_max"] == 55000
    assert payload["seniority"] == "intern"
    assert payload["remote"] is True
    implied_names = {skill["name"] for skill in payload["implied_skills"]}
    assert "Containerisation" in implied_names


def test_evaluate_job_quality_rejects_noise_with_reasons() -> None:
    response = _tool_call(
        "evaluate_job_quality",
        {
            "title": "Cancer Data Abstractor",
            "job_text": "Cancer registry role in the United States. CTR required.",
        },
    )

    result = response["result"]
    assert isinstance(result, dict)
    assert result["isError"] is False
    payload = _tool_payload(response)
    assert payload["decision"] == "reject"
    assert "off-topic-title" in payload["reasons"]


def test_score_job_fit_reports_missing_profile_without_crashing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    empty_profiles = tmp_path / "empty-profiles"
    empty_profiles.mkdir()
    monkeypatch.setenv("JOB_AGENT_PROFILES_DIR", str(empty_profiles))

    response = _tool_call("score_job_fit", {"job_text": JOB_TEXT})

    result = response["result"]
    assert isinstance(result, dict)
    assert result["isError"] is True
    payload = _tool_payload(response)
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == "PROFILE_NOT_CONFIGURED"


def test_malformed_json_returns_parse_error_and_can_continue() -> None:
    error = handle_line("{not-json")
    valid = handle_line(json.dumps(_request("tools/list", request_id=2)))

    assert error == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "Parse error"},
    }
    assert valid is not None
    assert valid["id"] == 2
    assert "result" in valid


def test_unknown_method_returns_method_not_found() -> None:
    response = handle_request(_request("resources/list", request_id=9))

    assert response == {
        "jsonrpc": "2.0",
        "id": 9,
        "error": {"code": -32601, "message": "Method not found"},
    }


def test_stdio_subprocess_initialize_round_trip() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    request = _request(
        "initialize",
        {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}},
        request_id=42,
    )

    process = subprocess.run(
        [sys.executable, "-m", "job_agent.mcp_server"],
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        cwd=ROOT,
        env=env,
        timeout=10,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    response = json.loads(process.stdout)
    assert response["id"] == 42
    assert response["result"]["serverInfo"]["name"] == "free-job-agent"
