"""One-click Ollama lifecycle helpers used by the dashboard.

The dashboard never assumes Ollama is running. Three small helpers let the UI
"set up AI" with a button click:

- ``start_ollama_server`` spawns ``ollama serve`` if the daemon isn't
  reachable. Safe to call repeatedly: if a server already responds, it's a
  no-op.
- ``pull_model`` runs ``ollama pull <model>`` in the background. Useful so
  the user doesn't need a terminal to download a fast chat model.
- ``ollama_install_status`` reports whether the binary is on PATH and
  whether the API is reachable.

Everything is local-only. No network calls beyond the local Ollama daemon
itself (which fetches models from ollama.com on the user's behalf, the same
way the CLI does).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from job_agent.polish import PolishOptions, available_ollama_models, is_ollama_reachable


@dataclass
class PullProgress:
    model: str = ""
    state: str = "idle"  # idle | running | success | failed
    started_at: str | None = None
    finished_at: str | None = None
    last_line: str = ""
    error: str | None = None
    log_tail: list[str] = field(default_factory=list)


_PULL_STATE: dict[str, PullProgress] = {}
_PULL_LOCK = threading.Lock()
_SERVE_PROCESS: Optional[subprocess.Popen] = None
_SERVE_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ollama_binary_path() -> Optional[str]:
    """Return the resolved ollama binary path, or None when not installed."""
    found = shutil.which("ollama")
    if found:
        return found
    # Windows default install location.
    candidates = [
        Path("C:/Users") / "Public" / "ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    import os as _os
    local_appdata = _os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe")
    for candidate in candidates:
        try:
            if candidate.exists():
                return str(candidate)
        except Exception:
            continue
    return None


def ollama_install_status(options: PolishOptions | None = None) -> dict:
    """Snapshot used by the dashboard's "AI setup" panel."""
    options = options or PolishOptions.from_env()
    binary = ollama_binary_path()
    reachable = is_ollama_reachable(options)
    models = available_ollama_models(options) if reachable else []
    return {
        "installed": bool(binary),
        "binary": binary or "",
        "reachable": reachable,
        "models": models,
        "base_url": options.base_url,
    }


def start_ollama_server(options: PolishOptions | None = None, *, wait_seconds: int = 6) -> dict:
    """Best-effort: launch ``ollama serve`` if no daemon answers yet.

    Returns a result dict the UI can render. Never raises. If Ollama is not
    installed at all, the caller gets ``ok=False, reason='not_installed'``.
    """
    options = options or PolishOptions.from_env()
    if is_ollama_reachable(options):
        return {"ok": True, "running": True, "started": False, "binary": ollama_binary_path() or ""}
    binary = ollama_binary_path()
    if not binary:
        return {
            "ok": False,
            "running": False,
            "started": False,
            "reason": "not_installed",
            "hint": "Install Ollama from https://ollama.com/download and try again.",
        }
    global _SERVE_PROCESS
    with _SERVE_LOCK:
        if _SERVE_PROCESS is not None and _SERVE_PROCESS.poll() is None:
            # Already launched this process; wait briefly for the daemon to come up.
            for _ in range(wait_seconds * 2):
                if is_ollama_reachable(options):
                    return {"ok": True, "running": True, "started": False, "binary": binary}
                time.sleep(0.5)
            return {"ok": False, "running": False, "started": False, "reason": "starting_slowly"}
        try:
            # CREATE_NO_WINDOW on Windows; otherwise detached on POSIX.
            kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if sys.platform.startswith("win"):
                creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                kwargs["creationflags"] = creationflags  # type: ignore[assignment]
            else:
                kwargs["start_new_session"] = True  # type: ignore[assignment]
            _SERVE_PROCESS = subprocess.Popen([binary, "serve"], **kwargs)
        except Exception as exc:
            return {"ok": False, "running": False, "started": False, "reason": str(exc)}
    for _ in range(wait_seconds * 2):
        if is_ollama_reachable(options):
            return {"ok": True, "running": True, "started": True, "binary": binary}
        time.sleep(0.5)
    return {"ok": False, "running": False, "started": True, "reason": "serve_started_but_not_responding"}


def pull_model(model: str, options: PolishOptions | None = None) -> dict:
    """Kick off ``ollama pull <model>`` in a background thread.

    Returns immediately. Progress is observable via :func:`pull_status`.
    """
    options = options or PolishOptions.from_env()
    model = (model or "").strip()
    if not model:
        return {"ok": False, "reason": "model_required"}
    binary = ollama_binary_path()
    if not binary:
        return {"ok": False, "reason": "not_installed"}
    if not is_ollama_reachable(options):
        # Try to launch the daemon first so the pull has something to talk to.
        start = start_ollama_server(options)
        if not start.get("ok"):
            return {"ok": False, "reason": start.get("reason", "daemon_unreachable")}

    with _PULL_LOCK:
        existing = _PULL_STATE.get(model)
        if existing and existing.state == "running":
            return {"ok": True, "running": True, "model": model, "state": existing.state}
        progress = PullProgress(model=model, state="running", started_at=_now_iso())
        _PULL_STATE[model] = progress

    def _runner() -> None:
        try:
            process = subprocess.Popen(
                [binary, "pull", model],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            with _PULL_LOCK:
                progress.state = "failed"
                progress.error = str(exc)
                progress.finished_at = _now_iso()
            return
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip()
            if not line:
                continue
            with _PULL_LOCK:
                progress.last_line = line
                progress.log_tail.append(line)
                if len(progress.log_tail) > 60:
                    progress.log_tail = progress.log_tail[-60:]
        exit_code = process.wait()
        with _PULL_LOCK:
            progress.state = "success" if exit_code == 0 else "failed"
            progress.finished_at = _now_iso()
            if exit_code != 0:
                progress.error = f"ollama pull exited with code {exit_code}"

    thread = threading.Thread(target=_runner, name=f"ollama-pull-{model}", daemon=True)
    thread.start()
    return {"ok": True, "running": True, "model": model, "state": "running"}


def pull_status(model: str | None = None) -> dict:
    with _PULL_LOCK:
        if model:
            progress = _PULL_STATE.get(model)
            return progress.__dict__.copy() if progress else {"model": model, "state": "idle"}
        return {key: value.__dict__.copy() for key, value in _PULL_STATE.items()}


def list_all_pulls() -> list[dict]:
    with _PULL_LOCK:
        return [value.__dict__.copy() for value in _PULL_STATE.values()]


__all__ = [
    "PullProgress",
    "ollama_binary_path",
    "ollama_install_status",
    "start_ollama_server",
    "pull_model",
    "pull_status",
    "list_all_pulls",
]
