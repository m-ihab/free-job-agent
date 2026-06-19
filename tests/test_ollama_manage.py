"""Behavioural tests for the Ollama lifecycle helpers.

No real subprocess / daemon is launched. ``shutil.which``, ``subprocess``,
and the reachability/model helpers are all monkeypatched.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import job_agent.ollama_manage as om
from job_agent.polish import PolishOptions


def _opts() -> PolishOptions:
    return PolishOptions(base_url="http://127.0.0.1:11434")


@pytest.fixture(autouse=True)
def _clear_pull_state():
    """Keep the module-level pull registry isolated between tests."""
    with om._PULL_LOCK:
        om._PULL_STATE.clear()
    yield
    with om._PULL_LOCK:
        om._PULL_STATE.clear()


# ── ollama_binary_path ────────────────────────────────────────────────────────


def test_binary_path_uses_which_when_on_path(monkeypatch):
    monkeypatch.setattr(om.shutil, "which", lambda name: "/usr/local/bin/ollama")
    assert om.ollama_binary_path() == "/usr/local/bin/ollama"


def test_binary_path_returns_none_when_not_installed(monkeypatch):
    monkeypatch.setattr(om.shutil, "which", lambda name: None)
    monkeypatch.setattr(om.Path, "exists", lambda self: False)
    monkeypatch.setenv("LOCALAPPDATA", "")
    assert om.ollama_binary_path() is None


# ── ollama_install_status ─────────────────────────────────────────────────────


def test_install_status_reports_full_state(monkeypatch):
    monkeypatch.setattr(om, "ollama_binary_path", lambda: "/bin/ollama")
    monkeypatch.setattr(om, "is_ollama_reachable", lambda options: True)
    monkeypatch.setattr(om, "available_ollama_models", lambda options: ["llama3.2:3b"])

    status = om.ollama_install_status(_opts())

    assert status["installed"] is True
    assert status["reachable"] is True
    assert status["models"] == ["llama3.2:3b"]


def test_install_status_skips_models_when_unreachable(monkeypatch):
    monkeypatch.setattr(om, "ollama_binary_path", lambda: "")
    monkeypatch.setattr(om, "is_ollama_reachable", lambda options: False)
    called = []
    monkeypatch.setattr(om, "available_ollama_models", lambda options: called.append(1) or [])

    status = om.ollama_install_status(_opts())

    assert status["installed"] is False
    assert status["models"] == []
    assert not called  # never probed models when the daemon is down


# ── start_ollama_server ───────────────────────────────────────────────────────


def test_start_server_noop_when_already_reachable(monkeypatch):
    monkeypatch.setattr(om, "is_ollama_reachable", lambda options: True)
    monkeypatch.setattr(om, "ollama_binary_path", lambda: "/bin/ollama")

    result = om.start_ollama_server(_opts())

    assert result["ok"] is True
    assert result["running"] is True
    assert result["started"] is False


def test_start_server_reports_not_installed(monkeypatch):
    monkeypatch.setattr(om, "is_ollama_reachable", lambda options: False)
    monkeypatch.setattr(om, "ollama_binary_path", lambda: None)

    result = om.start_ollama_server(_opts())

    assert result["ok"] is False
    assert result["reason"] == "not_installed"


def test_start_server_launches_and_detects_daemon(monkeypatch):
    reachable = {"v": False}
    monkeypatch.setattr(om, "is_ollama_reachable", lambda options: reachable["v"])
    monkeypatch.setattr(om, "ollama_binary_path", lambda: "/bin/ollama")
    monkeypatch.setattr(om, "_SERVE_PROCESS", None, raising=False)

    def _fake_popen(args, **kwargs):
        reachable["v"] = True  # daemon comes up immediately after launch
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(om.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(om.time, "sleep", lambda s: None)

    result = om.start_ollama_server(_opts(), wait_seconds=1)

    assert result["ok"] is True
    assert result["started"] is True


def test_start_server_reports_launch_failure(monkeypatch):
    monkeypatch.setattr(om, "is_ollama_reachable", lambda options: False)
    monkeypatch.setattr(om, "ollama_binary_path", lambda: "/bin/ollama")
    monkeypatch.setattr(om, "_SERVE_PROCESS", None, raising=False)

    def _boom(args, **kwargs):
        raise OSError("cannot spawn")

    monkeypatch.setattr(om.subprocess, "Popen", _boom)

    result = om.start_ollama_server(_opts())

    assert result["ok"] is False
    assert "cannot spawn" in result["reason"]


# ── pull_model ────────────────────────────────────────────────────────────────


def test_pull_model_requires_name(monkeypatch):
    assert om.pull_model("   ")["reason"] == "model_required"


def test_pull_model_not_installed(monkeypatch):
    monkeypatch.setattr(om, "ollama_binary_path", lambda: None)
    assert om.pull_model("llama3.2:3b")["reason"] == "not_installed"


def test_pull_model_short_circuits_when_already_installed(monkeypatch):
    monkeypatch.setattr(om, "ollama_binary_path", lambda: "/bin/ollama")
    monkeypatch.setattr(om, "is_ollama_reachable", lambda options: True)
    monkeypatch.setattr(om, "available_ollama_models", lambda options: ["llama3.2:3b"])

    result = om.pull_model("llama3.2:3b", _opts())

    assert result["ok"] is True
    assert result["already_installed"] is True
    assert result["state"] == "success"


def test_pull_model_starts_background_runner(monkeypatch):
    monkeypatch.setattr(om, "ollama_binary_path", lambda: "/bin/ollama")
    monkeypatch.setattr(om, "is_ollama_reachable", lambda options: True)
    monkeypatch.setattr(om, "available_ollama_models", lambda options: [])

    started = []

    class _FakeThread:
        def __init__(self, target, **kwargs):
            self._target = target

        def start(self):
            started.append(1)  # do NOT run the runner (would call subprocess)

    monkeypatch.setattr(om.threading, "Thread", _FakeThread)

    result = om.pull_model("mistral", _opts())

    assert result["ok"] is True
    assert result["state"] == "running"
    assert started
    assert om._PULL_STATE["mistral"].state == "running"


def test_pull_model_returns_running_if_already_in_progress(monkeypatch):
    monkeypatch.setattr(om, "ollama_binary_path", lambda: "/bin/ollama")
    monkeypatch.setattr(om, "is_ollama_reachable", lambda options: True)
    monkeypatch.setattr(om, "available_ollama_models", lambda options: [])
    with om._PULL_LOCK:
        om._PULL_STATE["mistral"] = om.PullProgress(model="mistral", state="running")

    result = om.pull_model("mistral", _opts())

    assert result["running"] is True
    assert result["state"] == "running"


# ── pull_status / list_all_pulls ─────────────────────────────────────────────


def test_pull_status_idle_for_unknown_model():
    assert om.pull_status("never-pulled") == {"model": "never-pulled", "state": "idle"}


def test_pull_status_returns_snapshot_for_known_model():
    with om._PULL_LOCK:
        om._PULL_STATE["m"] = om.PullProgress(model="m", state="success", last_line="done")

    snap = om.pull_status("m")

    assert snap["state"] == "success"
    assert snap["last_line"] == "done"


def test_list_all_pulls_returns_every_entry():
    with om._PULL_LOCK:
        om._PULL_STATE["a"] = om.PullProgress(model="a", state="running")
        om._PULL_STATE["b"] = om.PullProgress(model="b", state="success")

    all_pulls = om.list_all_pulls()

    states = {p["model"]: p["state"] for p in all_pulls}
    assert states == {"a": "running", "b": "success"}
