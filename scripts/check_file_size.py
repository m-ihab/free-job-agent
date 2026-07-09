#!/usr/bin/env python3
"""Pre-commit gate: block oversized source files.

Exit 2 if any passed file exceeds ``--max`` lines; print a warning (exit 0)
when a file exceeds ``--warn``. Keeps the 200-line design target enforceable
without fantasy: 300 warns, 800 blocks (docs/new/01-ENGINEERING-GUARDRAILS.md
G-7). Also the automatic enforcement of the app.js "boy-scout" split trigger.

Dependency-free (stdlib only) so it runs identically in pre-commit and CI.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def count_lines(path: Path) -> int:
    """Count newline-terminated lines without loading the whole file."""
    with path.open("rb") as fh:
        return sum(1 for _ in fh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max", type=int, default=800, help="hard cap (exit 2 over)")
    parser.add_argument("--warn", type=int, default=300, help="soft cap (warn over)")
    parser.add_argument("files", nargs="*", help="files to check")
    args = parser.parse_args(argv)

    blocked: list[tuple[str, int]] = []
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            continue
        try:
            n = count_lines(path)
        except OSError:
            continue
        if n > args.max:
            blocked.append((name, n))
        elif n > args.warn:
            print(f"warning: {name} is {n} lines (> {args.warn} soft cap)")

    for name, n in blocked:
        print(f"error: {name} is {n} lines (> {args.max} hard cap) — split it")
    return 2 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
