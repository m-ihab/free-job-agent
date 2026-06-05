#!/usr/bin/env python3
"""Generate a Claude-in-Chrome apply session from ready packets.

Usage:
    python scripts/chrome_apply_session.py
    python scripts/chrome_apply_session.py --min-score 75 --limit 5
    python scripts/chrome_apply_session.py --output my_session.md

The script reads ready packets from the local database, filters by fit score,
and writes a Markdown file with step-by-step Chrome apply instructions.
Paste each block into a Claude conversation with Chrome access to apply.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

# Allow running from the repo root without installing
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from job_agent.apply_bridge import generate_batch_instructions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Claude-in-Chrome apply instructions for ready packets."
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=65,
        help="Minimum fit score to include (default: 65)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of applications to generate (default: 10)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file path (default: .job_agent/chrome_apply_session.md)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        default=False,
        help="Do not automatically open the session file after generation",
    )
    args = parser.parse_args()

    print(f"Scanning for ready packets with score >= {args.min_score}...")
    candidates, out_path = generate_batch_instructions(
        min_score=args.min_score,
        limit=args.limit,
        output_path=args.output,
    )

    if not candidates:
        print("\nNo ready packets found.")
        print("Run the Autopilot or use `job-agent france-hunt` to generate packets first.")
        return

    print(f"\nFound {len(candidates)} application(s) ready:")
    for i, c in enumerate(candidates, 1):
        score = c.packet.fit_score or 0
        print(f"  {i}. [{score:.0f}/100] {c.job.title} at {c.job.company}")

    print(f"\nInstructions written to:\n  {out_path}")
    print("\nHow to apply:")
    print("  1. Make sure you are logged into LinkedIn (or relevant job board) in Chrome")
    print("  2. Open Claude.ai or Claude Code with computer-use / browser access")
    print("  3. Paste each application block into Claude")
    print("  4. Claude will navigate, fill the form, and wait for your approval before submitting")
    print("\nApply one at a time. Review Claude's summary before confirming each submission.")

    # Suggestion A: auto-open the session file so the user can copy-paste immediately
    if not args.no_open:
        try:
            webbrowser.open(out_path.resolve().as_uri())
            print(f"\nOpened session file in your default viewer.")
        except Exception:
            pass


if __name__ == "__main__":
    main()
