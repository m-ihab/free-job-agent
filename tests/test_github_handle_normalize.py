from __future__ import annotations

import pytest

import job_agent.portfolio_builder as portfolio_builder
import job_agent.profile_enrich as profile_enrich
from job_agent.github_handle import normalise_github_handle


def test_normalise_github_handle_accepts_handle_and_url() -> None:
    assert normalise_github_handle("@octocat") == "octocat"
    assert normalise_github_handle("https://github.com/octocat/") == "octocat"


@pytest.mark.parametrize("bad", ["", "bad/../handle", "https://evil.test/octocat", "octo_cat", "-octocat"])
def test_normalise_github_handle_rejects_invalid_values(bad: str) -> None:
    with pytest.raises(ValueError):
        normalise_github_handle(bad)


def test_profile_enrich_rejects_bad_handle_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_enrich, "_github_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))

    with pytest.raises(ValueError):
        profile_enrich.fetch_github_snapshot("bad/../handle")


def test_portfolio_repos_rejects_bad_handle_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    class Requests:
        @staticmethod
        def get(*args, **kwargs):
            raise AssertionError("network")

    monkeypatch.setattr(portfolio_builder, "requests", Requests)

    assert portfolio_builder.fetch_github_repos("bad/../handle") == []
