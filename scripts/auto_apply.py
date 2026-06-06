#!/usr/bin/env python3
"""CLI wrapper for the automated apply engine (Playwright, no API key needed).

Usage:
    python scripts/auto_apply.py
    python scripts/auto_apply.py --mode fill_and_confirm --min-score 70 --limit 10
    python scripts/auto_apply.py --mode full_auto --min-score 75 --limit 5
    python scripts/auto_apply.py --dry-run

Modes:
    fill_and_confirm  Playwright fills the form, then waits for your confirmation
                      before clicking Submit.  (default, recommended)
    full_auto         Playwright fills and submits automatically.  A 10-second
                      cancellation window appears before each submit.

Requirements:
    playwright    pip install playwright && playwright install chromium
    Chrome        must be installed and logged into the relevant job sites.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from job_agent.config import AppConfig
from job_agent.auto_apply import AutoApplySession, ApplyMode, ApplyEvent


def _confirm_terminal(event: ApplyEvent) -> bool:
    """Terminal confirmation gate for fill_and_confirm mode."""
    print()
    print("─" * 60)
    print(f"  READY TO SUBMIT: {event.message}")
    print()
    if event.summary:
        for line in event.summary.splitlines()[:20]:
            print(f"  {line}")
    print()
    while True:
        choice = input("  [S]ubmit / [K]skip / [Q]uit session? ").strip().lower()
        if choice in ("s", "submit", "y", "yes"):
            return True
        if choice in ("k", "skip", "n", "no"):
            return False
        if choice in ("q", "quit", "exit"):
            print("  Quitting session.")
            sys.exit(0)
        print("  Please enter S, K, or Q.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated Claude computer-use apply session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["fill_and_confirm", "full_auto"],
        default="fill_and_confirm",
        help="fill_and_confirm (default): Claude fills, you confirm each submit. "
             "full_auto: Claude fills and submits with a 10-s cancel window.",
    )
    parser.add_argument("--min-score", type=float, default=70.0,
                        help="Minimum fit score for packets (default: 70)")
    parser.add_argument("--limit", type=int, default=10,
                        help="Maximum applications per session (default: 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List ready packets without opening a browser.")
    args = parser.parse_args()

    config = AppConfig()

    if args.dry_run:
        from job_agent.apply_bridge import get_ready_candidates
        candidates = get_ready_candidates(min_score=args.min_score, limit=args.limit)
        if not candidates:
            print("No ready packets found. Run the autopilot or generate packets first.")
            return
        print(f"\nReady packets (score ≥ {args.min_score}):")
        for i, c in enumerate(candidates, 1):
            print(f"  {i}. [{c.packet.fit_score:.0f}/100] {c.job.title} @ {c.job.company}")
            print(f"     Apply URL: {c.job.apply_url or '(none)'}")
        return

    print(f"\nAuto-Apply — mode: {args.mode}  |  min score: {args.min_score}  |  limit: {args.limit}")
    print("Make sure Chrome is open and logged into the relevant job sites.")
    print("Press Ctrl+C at any time to cancel.\n")

    session = AutoApplySession(
        config=config,
        mode=ApplyMode(args.mode),
        min_score=args.min_score,
        limit=args.limit,
        headless=False,
    )
    session.run_in_background()

    try:
        while session.running or not session.progress_queue.empty():
            try:
                event = session.progress_queue.get(timeout=1.0)
            except Exception:
                continue

            kind = event.kind
            msg = event.message

            if kind == "progress":
                print(f"  → {msg}")
            elif kind == "pending_confirm":
                should_submit = _confirm_terminal(event)
                if should_submit:
                    session.confirm_submit()
                else:
                    session.skip_current()
            elif kind == "pre_submit":
                print(f"\n  ⚡ FULL AUTO: {msg}")
                print("  Press Enter to cancel within 10 seconds…")
                import threading
                cancel_event = threading.Event()
                def _wait_cancel():
                    input()
                    cancel_event.set()
                t = threading.Thread(target=_wait_cancel, daemon=True)
                t.start()
                if cancel_event.wait(timeout=10):
                    session.skip_current()
                    print("  Cancelled.")
                else:
                    print("  Submitting…")
            elif kind == "result":
                status = (event.data or {}).get("status", "")
                icon = "✓" if status == "submitted" else ("→" if status == "skipped" else "✗")
                print(f"  {icon} {msg}")
            elif kind in ("done", "error"):
                print(f"\n{'✓ Done' if kind == 'done' else '✗ Error'}: {msg}\n")
                break

    except KeyboardInterrupt:
        print("\n\nCancelling session…")
        session.cancel()
        time.sleep(1)


if __name__ == "__main__":
    main()
