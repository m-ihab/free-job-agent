"""Tests for opt-in subscription CLI LLM providers (job-public tasks only)."""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOB_AGENT_CLI_LLM", raising=False)
    monkeypatch.delenv("JOB_AGENT_CLI_LLM_TIMEOUT", raising=False)


def test_flag_off_returns_none_without_spawning(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_agent.llm_cli_providers as cli

    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: pytest.fail("spawned CLI"))

    assert cli.maybe_cli_json("public job", task="classify", max_output_tokens=64) is None


def test_non_public_task_never_spawns(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_agent.llm_cli_providers as cli

    monkeypatch.setenv("JOB_AGENT_CLI_LLM", "1")
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: pytest.fail("spawned CLI"))

    assert cli.maybe_cli_json("candidate evidence", task="fit_analysis", max_output_tokens=64) is None


def test_no_installed_cli_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_agent.llm_cli_providers as cli

    monkeypatch.setenv("JOB_AGENT_CLI_LLM", "1")
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: pytest.fail("spawned CLI"))

    assert cli.maybe_cli_json("public job", task="summarize", max_output_tokens=64) is None


def test_mocked_cli_stdout_returns_first_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_agent.llm_cli_providers as cli

    calls: list[tuple[list[str], dict[str, object]]] = []

    def _run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='status\n{"ok": true}\ndone', stderr="")

    monkeypatch.setenv("JOB_AGENT_CLI_LLM", "1")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(cli.subprocess, "run", _run)

    assert cli.maybe_cli_json("public job", task="classify", max_output_tokens=64) == {"ok": True}
    assert calls[0][0] == ["/bin/claude", "-p", "public job"]
    assert calls[0][1]["stdin"] is subprocess.DEVNULL
    assert calls[0][1]["timeout"] == 30


def test_codex_exec_is_used_when_claude_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_agent.llm_cli_providers as cli

    commands: list[list[str]] = []

    def _run(command: list[str], **kwargs: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setenv("JOB_AGENT_CLI_LLM", "1")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/bin/codex" if name == "codex" else None)
    monkeypatch.setattr(cli.subprocess, "run", _run)

    assert cli.maybe_cli_json("public job", task="classify", max_output_tokens=64) == {"ok": True}
    assert commands == [["/bin/codex", "exec", "public job"]]


def test_windows_cmd_shim_uses_powershell_file_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_agent.llm_cli_providers as cli

    commands: list[list[str]] = []
    prompt = 'public job" & echo INJECTED & rem "'

    def _which(name: str) -> str | None:
        paths = {
            "claude": r"C:\Tools\claude.CMD",
            "powershell": r"C:\Windows\powershell.exe",
        }
        return paths.get(name)

    def _run(command: list[str], **kwargs: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setenv("JOB_AGENT_CLI_LLM", "1")
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.shutil, "which", _which)
    monkeypatch.setattr(cli.os.path, "isfile", lambda path: path == r"C:\Tools\claude.ps1")
    monkeypatch.setattr(cli.subprocess, "run", _run)

    assert cli.maybe_cli_json(prompt, task="classify", max_output_tokens=64) == {"ok": True}
    assert commands == [[
        r"C:\Windows\powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        r"C:\Tools\claude.ps1",
        "-p",
        prompt,
    ]]


@pytest.mark.parametrize(
    "outcome",
    [
        subprocess.TimeoutExpired(cmd="claude", timeout=30),
        SimpleNamespace(returncode=0, stdout="not json", stderr=""),
    ],
)
def test_timeout_or_garbage_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    outcome: BaseException | SimpleNamespace,
) -> None:
    import job_agent.llm_cli_providers as cli

    def _run(*args: object, **kwargs: object) -> SimpleNamespace:
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setenv("JOB_AGENT_CLI_LLM", "1")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(cli.subprocess, "run", _run)

    assert cli.maybe_cli_json("public job", task="summarize", max_output_tokens=64) is None


def test_ai_agent_uses_cli_before_cloud_when_ollama_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_agent.ai_agent as ai
    from job_agent.polish import PolishOptions

    class _DownRequests:
        @staticmethod
        def post(*args: object, **kwargs: object) -> None:
            raise ConnectionError("ollama down")

    monkeypatch.setattr(ai, "requests", _DownRequests)
    monkeypatch.setattr(ai.llm_cli_providers, "maybe_cli_json", lambda *args, **kwargs: {"via": "cli"})
    monkeypatch.setattr(
        ai.llm_providers,
        "maybe_cloud_json",
        lambda *args, **kwargs: pytest.fail("cloud called before successful CLI"),
    )

    result = ai._call_ollama_json("public job", PolishOptions(enabled=True), task="classify")

    assert result == {"via": "cli"}


def test_ai_agent_tries_cloud_when_cli_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_agent.ai_agent as ai
    from job_agent.polish import PolishOptions

    class _DownRequests:
        @staticmethod
        def post(*args: object, **kwargs: object) -> None:
            raise ConnectionError("ollama down")

    calls: list[str] = []
    monkeypatch.setattr(ai, "requests", _DownRequests)
    monkeypatch.setattr(
        ai.llm_cli_providers,
        "maybe_cli_json",
        lambda *args, **kwargs: calls.append("cli") or None,
    )
    monkeypatch.setattr(
        ai.llm_providers,
        "maybe_cloud_json",
        lambda *args, **kwargs: calls.append("cloud") or {"via": "cloud"},
    )

    result = ai._call_ollama_json("public job", PolishOptions(enabled=True), task="summarize")

    assert result == {"via": "cloud"}
    assert calls == ["cli", "cloud"]


def test_ai_agent_is_available_with_cli_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_agent.ai_agent as ai

    monkeypatch.setattr(ai, "is_ollama_reachable", lambda options=None: False)
    monkeypatch.setattr(ai.llm_cli_providers, "cli_enabled", lambda: True)
    monkeypatch.setattr(ai.llm_providers, "cloud_enabled", lambda: False)

    assert ai.is_available() is True
