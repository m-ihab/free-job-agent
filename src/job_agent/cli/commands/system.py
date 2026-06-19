"""System-level command handlers (dashboard UI, readiness, exports)."""
from __future__ import annotations

import argparse
import shutil

from job_agent.exporters.internship_workbook import export_applied_internships
from job_agent.polish import PolishOptions, ollama_status

from job_agent.cli.commands._common import (
    Panel,
    _fail,
    _find_local_tool,
    _load_config,
    console,
)


def _handle_ui(args: argparse.Namespace) -> None:
    from job_agent.ui.server import run_server

    run_server(host=args.host, port=args.port, open_browser=not args.no_open)


def _handle_ai_status(args: argparse.Namespace) -> None:
    status = ollama_status(PolishOptions.from_env())
    compiler_tools = {
        "pdflatex": shutil.which("pdflatex"),
        "latexmk": shutil.which("latexmk"),
        "perl": _find_local_tool("perl"),
        "node": _find_local_tool("node"),
        "npm": _find_local_tool("npm"),
        "openclaw": _find_local_tool("openclaw"),
    }
    lines = [
        f"Ollama reachable: {'yes' if status['reachable'] else 'no'}",
        f"Selected heavy model: {status['selected_model'] or '-'}",
        f"Selected fast chat model: {status.get('selected_fast_model') or '-'}",
        f"Installed models: {', '.join(status['models']) if status['models'] else '-'}",
        f"Ollama polish opt-in: {'enabled' if status['enabled'] else 'disabled'}",
        "",
        "Local tools:",
    ]
    for name, path in compiler_tools.items():
        lines.append(f"- {name}: {path or 'not on PATH'}")
    if not compiler_tools["npm"] or not compiler_tools["openclaw"]:
        lines.append("")
        lines.append("If npm/openclaw are installed but shown as missing, restart PowerShell or add their install folder to PATH.")
    console.print(Panel("\n".join(lines), title="AI / local-tool readiness"))


def _handle_export_internships(args: argparse.Namespace) -> None:
    config = _load_config()
    try:
        workbook_path, count = export_applied_internships(config, workbook_path=args.workbook, sheet_name=args.sheet)
    except Exception as exc:
        _fail(f"Failed to export internship workbook: {exc}")
    console.print(
        Panel(
            f"Exported {count} applied internship(s)\nWorkbook: {workbook_path}",
            title="Internship export complete",
        )
    )
