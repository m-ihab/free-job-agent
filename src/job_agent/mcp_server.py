"""Minimal read-only MCP server exposing the local job-fit engine over stdio."""
from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from typing import IO, Final, TypeAlias, cast

from job_agent.config import AppConfig
from job_agent.filters import FilterConfig, apply_filters
from job_agent.normalizer import normalize
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, MasterCV, Skill
from job_agent.schemas.job import JobListing
from job_agent.scorer import explain_score
from job_agent.search_quality import assess_search_quality
from job_agent.skill_extractor import extract_implied_skills
from job_agent.validators import load_profile_bundle

JsonObject: TypeAlias = dict[str, object]
ToolHandler: TypeAlias = Callable[[Mapping[str, object]], JsonObject]

PROTOCOL_VERSION: Final = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS: Final = {
    "2024-11-05", "2025-03-26", "2025-06-18", PROTOCOL_VERSION,
}
SERVER_INFO: Final[JsonObject] = {"name": "free-job-agent", "version": "0.3.0"}
READ_ONLY: Final[JsonObject] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def _schema(properties: JsonObject, required: list[str]) -> JsonObject:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_TEXT_FIELD: JsonObject = {"type": "string", "minLength": 1}
TOOLS: Final[list[JsonObject]] = [
    {
        "name": "score_job_fit",
        "description": "Score pasted job text against the configured candidate profile.",
        "inputSchema": _schema(
            {name: dict(_TEXT_FIELD) for name in ("job_text", "title", "company", "location")},
            ["job_text"],
        ),
        "annotations": dict(READ_ONLY),
    },
    {
        "name": "extract_job_intel",
        "description": "Extract deterministic normalized fields and implied skills from job text.",
        "inputSchema": _schema({"job_text": dict(_TEXT_FIELD)}, ["job_text"]),
        "annotations": dict(READ_ONLY),
    },
    {
        "name": "evaluate_job_quality",
        "description": "Evaluate hard filters and search-noise rejection reasons for job text.",
        "inputSchema": _schema(
            {"job_text": dict(_TEXT_FIELD), "title": dict(_TEXT_FIELD)}, ["job_text"]
        ),
        "annotations": dict(READ_ONLY),
    },
]


def _required_text(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(arguments: Mapping[str, object], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value.strip() or None


def _build_job(arguments: Mapping[str, object]) -> JobListing:
    job = JobListing(
        source="mcp",
        raw_text=_required_text(arguments, "job_text"),
        title=_optional_text(arguments, "title") or "[To Be Parsed]",
        company=_optional_text(arguments, "company") or "[To Be Parsed]",
        location=_optional_text(arguments, "location"),
    )
    return normalize(job)


def _score_job_fit(arguments: Mapping[str, object]) -> JsonObject:
    job = _build_job(arguments)
    profile, _master_cv, _qa_profile = load_profile_bundle(AppConfig.load())
    return cast(JsonObject, explain_score(job, profile))


def _extract_job_intel(arguments: Mapping[str, object]) -> JsonObject:
    job = _build_job(arguments)
    contact = ContactInfo(name="Job Intel", email="job-intel@invalid.local")
    profile = CandidateProfile(contact=contact, skills=[Skill(name=name) for name in job.tech_stack])
    implied = extract_implied_skills(profile, MasterCV(contact=contact))
    return {
        "title": job.title,
        "location": job.location,
        "tech_stack": job.tech_stack,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "seniority": job.seniority,
        "remote": job.remote,
        "work_mode": job.work_mode,
        "extracted_skills": job.tech_stack,
        "implied_skills": [
            {"name": skill.name, "implied_by": skill.implied_by, "category": skill.category}
            for skill in implied
        ],
    }


def _evaluate_job_quality(arguments: Mapping[str, object]) -> JsonObject:
    job = _build_job(arguments)
    try:
        profile, _master_cv, _qa_profile = load_profile_bundle(AppConfig.load())
    except (FileNotFoundError, ValueError):
        profile = None
    filters = apply_filters(job, FilterConfig(), profile)
    quality = assess_search_quality(job, query="data scientist", location=job.location or "")
    flags = [str(flag) for flag in quality.get("flags", [])]
    reasons = list(dict.fromkeys([*filters.reasons, *flags]))
    relevant = bool(quality.get("relevant"))
    if not relevant and not flags:
        reasons.append(f"search-quality-score:{int(quality.get('score', 0))}")
    passed = filters.passed and relevant
    return {
        "decision": "pass" if passed else "reject",
        "passed": passed,
        "reasons": reasons,
        "risk_flags": filters.risk_flags,
        "search_quality": {
            "score": int(quality.get("score", 0)),
            "role_family": str(quality.get("role_family", "")),
            "contract": str(quality.get("contract", "")),
            "flags": flags,
        },
    }


_HANDLERS: Final[dict[str, ToolHandler]] = {
    "score_job_fit": _score_job_fit,
    "extract_job_intel": _extract_job_intel,
    "evaluate_job_quality": _evaluate_job_quality,
}


def _error(request_id: object, code: int, message: str) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(payload: JsonObject, *, is_error: bool = False) -> JsonObject:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call_tool(request_id: object, params: object) -> JsonObject:
    if not isinstance(params, dict):
        return _error(request_id, -32602, "Invalid tools/call params")
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or name not in _HANDLERS:
        return _error(request_id, -32602, f"Unknown tool: {name}")
    if not isinstance(arguments, dict):
        return _error(request_id, -32602, "Tool arguments must be an object")
    try:
        result = _HANDLERS[name](arguments)
        return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
    except FileNotFoundError as exc:
        payload: JsonObject = {
            "error": {
                "code": "PROFILE_NOT_CONFIGURED",
                "message": "Candidate profile bundle is not configured.",
                "details": str(exc),
            }
        }
    except ValueError as exc:
        payload = {"error": {"code": "INVALID_ARGUMENT", "message": str(exc)}}
    except Exception as exc:  # Protocol boundary: one tool failure must not stop the server.
        payload = {"error": {"code": "TOOL_EXECUTION_ERROR", "message": str(exc)}}
    return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(payload, is_error=True)}


def handle_request(request: Mapping[str, object]) -> JsonObject | None:
    """Handle one decoded JSON-RPC request; notifications return no response."""
    request_id = request.get("id")
    method = request.get("method")
    if not isinstance(method, str):
        return _error(request_id, -32600, "Invalid Request")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        params = request.get("params", {})
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = requested if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        result: JsonObject = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        return _call_tool(request_id, request.get("params"))
    return _error(request_id, -32601, "Method not found")


def handle_line(line: str) -> JsonObject | None:
    """Decode and handle one newline-delimited JSON-RPC message."""
    try:
        decoded: object = json.loads(line)
    except json.JSONDecodeError:
        return _error(None, -32700, "Parse error")
    if not isinstance(decoded, dict):
        return _error(None, -32600, "Invalid Request")
    return handle_request(cast(JsonObject, decoded))


def serve(stdin: IO[str], stdout: IO[str]) -> None:
    """Serve newline-delimited JSON-RPC until stdin closes."""
    for line in stdin:
        if not line.strip():
            continue
        response = handle_line(line)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            stdout.flush()


def main() -> None:
    serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
