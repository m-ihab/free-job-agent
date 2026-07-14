"""Contract tests for the public free-job-agent skill document."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from job_agent.cli.main import LocalCLIApp
from job_agent.mcp_server import TOOLS

ROOT = Path(__file__).parent.parent
SKILL_PATH = ROOT / "skills" / "free-job-agent" / "SKILL.md"


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _registered_cli_commands() -> set[str]:
    parser = LocalCLIApp().build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return set(subparsers.choices)


def _defined_mcp_tools() -> set[str]:
    return {str(tool["name"]) for tool in TOOLS}


def test_skill_document_exists() -> None:
    assert SKILL_PATH.is_file()


def test_documented_cli_commands_are_registered() -> None:
    documented = set(re.findall(r"`job-agent\s+([a-z0-9][a-z0-9-]*)\b[^`]*`", _skill_text()))

    assert documented
    assert documented <= _registered_cli_commands()


def test_documented_mcp_tools_match_server_registry() -> None:
    documented = set(re.findall(r"^### `([a-z][a-z0-9_]*)`$", _skill_text(), re.MULTILINE))

    assert documented == _defined_mcp_tools()
