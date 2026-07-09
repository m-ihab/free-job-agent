"""Local CI-equivalent gate — run before every push (wired into .git/hooks/pre-push).

Mirrors the reproducible checks of .github/workflows/ci.yml so a push cannot go
red on anything catchable locally: compileall syntax floor, ruff, the BLE
safety-path gate, mypy, stylelint, eslint. Born from the 2026-07-09 incident
where a commit passed pytest locally but was pushed with mypy + eslint failures.

Pytest stays CI's job by default (the full suite exceeds 10 minutes locally);
pass --full to include it.

Usage:
    python scripts/preflight.py [--full]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _utf8_stdout() -> None:
    # Windows cp1252 consoles crash on unicode in tool output (recurring bug
    # class in this repo) — force utf-8 with replacement.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def _run(name: str, cmd: list[str]) -> bool:
    print(f"[preflight] running {name} ...", flush=True)
    try:
        result = subprocess.run(cmd, cwd=ROOT)
    except FileNotFoundError:
        print(f"[preflight] FAIL {name}: command not found: {cmd[0]}")
        return False
    if result.returncode != 0:
        print(f"[preflight] FAIL {name} (exit {result.returncode})")
        return False
    print(f"[preflight] OK   {name}")
    return True


def main(argv: list[str]) -> int:
    _utf8_stdout()
    py = sys.executable
    checks: list[tuple[str, list[str]]] = [
        ("syntax gate (compileall)", [py, "-m", "compileall", "-q", "src", "tests"]),
        ("ruff", [py, "-m", "ruff", "check", "src", "tests"]),
        (
            "ruff BLE (safety paths)",
            [
                py,
                "-m",
                "ruff",
                "check",
                "src/job_agent/ui/security.py",
                "src/job_agent/utils/net.py",
                "--select",
                "BLE",
            ],
        ),
        ("mypy", [py, "-m", "mypy", "src"]),
    ]
    npm = shutil.which("npm")
    if npm and (ROOT / "node_modules").exists():
        checks.append(("stylelint", [npm, "run", "lint:css"]))
        checks.append(("eslint", [npm, "run", "lint:js"]))
    else:
        print("[preflight] WARN: npm or node_modules unavailable — frontend lint left to CI")
    if "--full" in argv:
        checks.append(("pytest (full suite)", [py, "-m", "pytest", "-q"]))

    failed = [name for name, cmd in checks if not _run(name, cmd)]
    if failed:
        print(f"[preflight] BLOCKED — {len(failed)} gate(s) failed: {', '.join(failed)}")
        return 1
    print("[preflight] all gates green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
