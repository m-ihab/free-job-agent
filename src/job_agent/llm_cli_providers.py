"""Opt-in subscription CLI LLM fallback for job-public data only.

Claude Code and Codex are US-hosted services. They may receive only prompts
built exclusively from public job postings. Candidate profiles, CVs, evidence
store data, letters, chat, and other personal data must never be sent through
these providers. ``is_job_public_task`` is enforced before every subprocess
call. The feature is off unless ``JOB_AGENT_CLI_LLM=1`` is set.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

from job_agent.agent_core import AgentRoute, estimate_tokens, record_trace
from job_agent.llm_providers import _parse_json, is_job_public_task

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
_CLI_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude", ("-p",)),
    ("codex", ("exec",)),
)


@dataclass(frozen=True)
class CLIProvider:
    """One installed non-interactive agent CLI."""

    name: str
    executable: str
    prompt_args: tuple[str, ...]

    def command(self, prompt: str) -> list[str]:
        return [self.executable, *self.prompt_args, prompt]


def enabled() -> bool:
    """Return whether the subscription CLI fallback is explicitly enabled."""
    return os.environ.get("JOB_AGENT_CLI_LLM", "").strip().lower() in {"1", "true", "yes", "on"}


def available_cli_providers() -> list[CLIProvider]:
    """Return installed CLIs in fallback order (Claude Code, then Codex)."""
    providers: list[CLIProvider] = []
    for name, prompt_args in _CLI_SPECS:
        executable = shutil.which(name)
        if executable:
            providers.append(CLIProvider(name, executable, prompt_args))
    return providers


def cli_enabled() -> bool:
    """Return whether the flag is on and at least one supported CLI is installed."""
    return enabled() and bool(available_cli_providers())


def _timeout() -> int:
    try:
        return int(os.environ.get("JOB_AGENT_CLI_LLM_TIMEOUT", str(DEFAULT_TIMEOUT)))
    except ValueError:
        return DEFAULT_TIMEOUT


def _parse_first_json(text: str) -> Optional[dict]:
    parsed = _parse_json(text)
    if parsed is not None:
        return parsed
    cleaned = text or ""
    decoder = json.JSONDecoder()
    for index, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _subprocess_command(provider: CLIProvider, prompt: str) -> Optional[list[str]]:
    """Build an argument-safe command, including for Windows npm shims."""
    direct = provider.command(prompt)
    if sys.platform != "win32" or os.path.splitext(provider.executable)[1].lower() not in {".cmd", ".bat"}:
        return direct
    script = os.path.splitext(provider.executable)[0] + ".ps1"
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if not powershell or not os.path.isfile(script):
        logger.info("subscription CLI provider %s has no safe Windows launcher", provider.name)
        return None
    return [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        script,
        *provider.prompt_args,
        prompt,
    ]


def _invoke_cli(provider: CLIProvider, prompt: str, *, task: str) -> Optional[str]:
    """Invoke one CLI only after independently enforcing the privacy gate."""
    if not is_job_public_task(task):
        return None
    command = _subprocess_command(provider, prompt)
    if command is None:
        return None
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_timeout(),
        check=False,
    )
    if completed.returncode != 0:
        logger.info("subscription CLI provider %s exited with status %s", provider.name, completed.returncode)
        return None
    return completed.stdout


def maybe_cli_json(prompt: str, *, task: str, max_output_tokens: int = 512) -> Optional[dict]:
    """Try installed subscription CLIs for a job-public task; return None on failure."""
    if not enabled() or not is_job_public_task(task):
        return None
    for provider in available_cli_providers():
        route = AgentRoute(
            task=task,
            tier="L2",
            model=f"cli:{provider.name}",
            reason="subscription CLI fallback (job-public task)",
            estimated_input_tokens=estimate_tokens(prompt),
            max_output_tokens=max_output_tokens,
        )
        started = time.perf_counter()
        try:
            content = _invoke_cli(provider, prompt, task=task)
        except Exception as exc:
            record_trace(
                route,
                ok=False,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )
            logger.info("subscription CLI provider %s failed (%s); trying next", provider.name, type(exc).__name__)
            continue
        parsed = _parse_first_json(content or "")
        record_trace(
            route,
            ok=parsed is not None,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error="" if parsed is not None else "invalid or empty json",
        )
        if parsed is not None:
            return parsed
    return None
