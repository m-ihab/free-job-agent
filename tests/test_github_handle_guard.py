"""The GitHub handle resolver sanitizes input so it can't inject URL path/query."""
from __future__ import annotations

from types import SimpleNamespace

from job_agent.ui.server import _resolve_github_handle


def _cfg():
    return SimpleNamespace(profiles_dir=None)


def test_valid_handle_passes():
    assert _resolve_github_handle(_cfg(), {"handle": "octocat"}) == "octocat"
    assert _resolve_github_handle(_cfg(), {"handle": "@octocat"}) == "octocat"


def test_injection_attempts_are_rejected():
    for bad in ["octocat/repos?x=1", "../etc", "a b", "user/../admin", "x?y", "evil#frag"]:
        assert _resolve_github_handle(_cfg(), {"handle": bad}) == ""


def test_missing_handle_is_empty():
    assert _resolve_github_handle(_cfg(), {}) == ""
