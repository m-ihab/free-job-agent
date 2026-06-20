"""Tests for search relevance filtering and France Travail diagnostics.

Negative fixtures cover off-topic results for a ``data scientist`` / internships
query; the FT helpers surface sanitized params + response body on 400s.
"""
from __future__ import annotations

import pytest

from job_agent.intake.sources import base
from job_agent.intake.sources.base import FreeApiSearch, _post_filter
from job_agent.intake.sources.francetravail import sanitize_ft_params
from job_agent.schemas.job import JobListing


def _job(title: str, *, location: str = "Paris", description: str = "", remote: bool = False) -> JobListing:
    return JobListing(title=title, company="X", location=location, description=description, remote=remote)


def _search(**kw) -> FreeApiSearch:
    return FreeApiSearch(
        source=kw.pop("source", "test"),
        query=kw.pop("query", "data scientist"),
        location=kw.pop("location", "Paris"),
        **kw,
    )


# ── relevance gate: the exact bad results stay out ───────────────────────────


@pytest.mark.parametrize("bad_title", [
    "Informaticien / Informaticienne",
    "ALTERNANCE Master SI/Finance Business",
])
def test_post_filter_drops_known_bad_titles(bad_title):
    # With the query filter on (the path LBA now always uses), off-topic rows
    # that don't match the "data scientist" query are dropped.
    jobs = [_job(bad_title)]
    kept = _post_filter(jobs, _search(), apply_query_filter=True)
    assert kept == [], f"{bad_title!r} should be filtered out of the shortlist"


def test_post_filter_keeps_a_strong_match():
    jobs = [_job("Data Scientist", description="machine learning python pandas data pipeline")]
    kept = _post_filter(jobs, _search(), apply_query_filter=True)
    assert len(kept) == 1


def test_post_filter_keeps_legit_adjacent_role():
    # Recall-safety: a plain engineering role for a matching query must survive
    # (the data-tuned relevance score must NOT be a hard cutoff).
    jobs = [_job("Python Platform Engineer", description="backend python services")]
    kept = _post_filter(jobs, _search(query="python"), apply_query_filter=True)
    assert len(kept) == 1


# ── France Travail param sanitization ────────────────────────────────────────


def test_sanitize_ft_params_redacts_secrets_keeps_search_params():
    params = {"motsCles": "data scientist", "range": "0-49", "client_secret": "abc123", "token": "xyz"}
    safe = sanitize_ft_params(params)
    assert safe["motsCles"] == "data scientist"
    assert safe["range"] == "0-49"
    assert safe["client_secret"] == "***redacted***"
    assert safe["token"] == "***redacted***"


# ── France Travail 400 surfaces sanitized params + body ──────────────────────


class _FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": "application/json"}
        self.content = text.encode() or b"x"

    def raise_for_status(self):
        if self.status_code >= 400:
            err = base.requests.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err

    def json(self):
        return {}


def test_ft_400_error_includes_sanitized_params_and_body(monkeypatch):
    from job_agent.intake.sources import francetravail as ft

    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        return _FakeResp(400, text='{"message":"Parametre typeContrat invalide"}')

    monkeypatch.setattr(base.requests, "get", fake_get)
    monkeypatch.setattr(ft, "france_travail_token", lambda **kw: "fake-token")

    with pytest.raises(base.FreeApiError) as excinfo:
        ft.fetch(_search(query="data scientist", contract_type="stage_and_alternance"))

    msg = str(excinfo.value)
    assert "HTTP 400" in msg
    assert "Sanitized params" in msg
    assert "typeContrat invalide" in msg  # the FT response body is surfaced


def test_ft_never_sends_invalid_typecontrat_for_internships(monkeypatch):
    """Stage/alternance must not be sent as a typeContrat param (FT rejects
    STG/CA1/CA2); contract filtering happens post-hoc in _post_filter."""
    from job_agent.intake.sources import francetravail as ft

    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(params or {})
        return _FakeResp(200, text='{"resultats": []}')

    # 200 path returns {} from _FakeResp.json(); patch json to a real payload.
    def fake_get_ok(url, params=None, headers=None, timeout=None):
        seen.clear()
        seen.update(params or {})
        resp = _FakeResp(200)
        resp.json = lambda: {"resultats": []}
        return resp

    monkeypatch.setattr(base.requests, "get", fake_get_ok)
    monkeypatch.setattr(ft, "france_travail_token", lambda **kw: "fake-token")

    ft.fetch(_search(query="data scientist", contract_type="stage_and_alternance"))

    assert "typeContrat" not in seen, f"typeContrat must not be sent to FT; got {seen.get('typeContrat')!r}"
    # The fetch range is widened so post-filtering still yields internships.
    assert seen.get("range", "0-0").endswith("-24") or seen.get("range") == "0-24"
