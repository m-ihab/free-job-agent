"""Guard canonical apply-mode wording in user and agent docs."""
from __future__ import annotations

from pathlib import Path

import pytest

DOCS = [
    Path("CLAUDE.md"),
    Path("README.md"),
    Path("AGENTS.md"),
    Path("PLAN.md"),
    Path("SESSION-HISTORY.md"),
    Path("docs/AI-TOOLING.md"),
    Path("docs/architecture.md"),
    Path("docs/FULL_AUTO_CONTRACT.md"),
    Path("docs/france_market.md"),
    Path("docs/free_sources.md"),
    Path("docs/HEALTH-REPORT.md"),
    Path("docs/merge_notes.md"),
    Path("docs/SECURITY-AUDIT.md"),
]

BLOCKED = [
    "full auto asks for confirmation",
    "full auto is a separate armed product mode",
    "packets are prepared but applications are never submitted",
    "applications are never submitted",
    "never auto-submit without human review",
]

ALLOWED_CONTEXT = [
    "stale",
    "old wording",
    "old \"never auto-submit",
]


def test_canonical_full_auto_phrasing_is_present():
    # docs/ is local-only (untracked); CI checkouts don't have this file.
    path = Path("docs/FULL_AUTO_CONTRACT.md")
    if not path.exists():
        pytest.skip("docs/FULL_AUTO_CONTRACT.md is local-only, absent in CI checkouts")
    text = path.read_text(encoding="utf-8").casefold()

    assert "full auto off" in text
    assert "fill_and_confirm" in text
    assert "full auto on" in text
    assert "full_auto" in text
    assert "detection is allowed" in text
    assert "bypass is not" in text


def test_stale_full_auto_guidance_does_not_reappear():
    offenders: list[str] = []
    for path in DOCS:
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            lower = line.casefold()
            if any(blocked in lower for blocked in BLOCKED) and not any(
                allowed in lower for allowed in ALLOWED_CONTEXT
            ):
                offenders.append(f"{path}:{number}: {line.strip()}")

    assert offenders == []
