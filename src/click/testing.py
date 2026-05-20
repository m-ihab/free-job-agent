"""Minimal ``click.testing`` replacement."""
from __future__ import annotations

import contextlib
import io
import sys
from dataclasses import dataclass


@dataclass
class Result:
    exit_code: int
    output: str
    exception: Exception | None = None


class CliRunner:
    def invoke(self, app, args=None, input: str | None = None):
        args = list(args or [])
        stdout = io.StringIO()
        stderr = io.StringIO()
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(input or "")
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = app.invoke(args)
            return Result(exit_code=exit_code, output=stdout.getvalue() + stderr.getvalue())
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            return Result(exit_code=code, output=stdout.getvalue() + stderr.getvalue(), exception=exc)
        except Exception as exc:  # pragma: no cover - surfaced in failing tests
            return Result(exit_code=1, output=stdout.getvalue() + stderr.getvalue(), exception=exc)
        finally:
            sys.stdin = old_stdin
