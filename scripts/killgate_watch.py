#!/usr/bin/env python3
"""Weekly JobSignal kill-gate watch runner (see job_agent.killgate_watch).

Usage:  python scripts/killgate_watch.py     (exit 2 = gate tripped)
Cron/Task Scheduler: run weekly; alert on non-zero exit.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from job_agent.killgate_watch import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
