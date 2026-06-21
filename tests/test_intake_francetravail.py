"""Behavioural tests for France Travail / La bonne alternance intake.

Monkeypatches the ``requests`` the connector modules call with canned JSON, and
redirects the OAuth token-cache to a temp dir, so no real OAuth or network ever
happens. Asserts token acquisition, endpoint registry overrides, client request
mapping, error handling, and job mapping for both connectors.
"""
from __future__ import annotations

import json

import pytest
import requests

from job_agent.intake import france_travail_auth as ft_auth
from job_agent.intake import france_travail_client as ft_client
from job_agent.intake import france_travail_endpoints as ft_ep
from job_agent.intake.sources import labonnealternance as lba
from job_agent.intake.sources.base import FreeApiSearch


# ── fakes ────────────────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, *, json_data=None, status_code=200, headers=None, text="OK"):
        self._json = json_data
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self._text = text
        self.content = (text or "").encode("utf-8")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err


@pytest.fixture
def ft_creds(monkeypatch, tmp_path):
    monkeypatch.setenv("FRANCE_TRAVAIL_CLIENT_ID", "client-123")
    monkeypatch.setenv("FRANCE_TRAVAIL_CLIENT_SECRET", "secret-xyz")
    monkeypatch.setenv("JOB_AGENT_API_CACHE_DIR", str(tmp_path / "cache"))
    # No configured scope, so the candidate list drives the loop.
    monkeypatch.delenv("FRANCE_TRAVAIL_SCOPE", raising=False)


# ── auth: token acquisition ──────────────────────────────────────────────────

def test_token_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("FRANCE_TRAVAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("FRANCE_TRAVAIL_CLIENT_SECRET", raising=False)
    with pytest.raises(ValueError, match="Missing France Travail OAuth credentials"):
        ft_auth.france_travail_token(timeout=5, use_cache=False, cache_ttl_hours=0)


def test_token_returns_access_token(ft_creds, monkeypatch):
    monkeypatch.setattr(
        ft_auth.requests, "post",
        lambda *a, **k: FakeResponse(json_data={"access_token": "tok-abc"}),
    )
    token = ft_auth.france_travail_token(timeout=5, use_cache=False, cache_ttl_hours=0)
    assert token == "tok-abc"


def test_token_skips_4xx_scope_and_tries_next(ft_creds, monkeypatch):
    calls = {"n": 0}

    def _post(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse(status_code=400, json_data={"error": "invalid_scope"})
        return FakeResponse(json_data={"access_token": "tok-second"})

    monkeypatch.setattr(ft_auth.requests, "post", _post)
    token = ft_auth.france_travail_token(timeout=5, use_cache=False, cache_ttl_hours=0)
    assert token == "tok-second"
    assert calls["n"] >= 2


def test_token_non_json_response_collected_as_error(ft_creds, monkeypatch):
    monkeypatch.setattr(
        ft_auth.requests, "post",
        lambda *a, **k: FakeResponse(json_data=None, headers={"Content-Type": "text/html"}, text="<html>"),
    )
    with pytest.raises(ValueError, match="non-JSON response"):
        ft_auth.france_travail_token(timeout=5, use_cache=False, cache_ttl_hours=0)


def test_token_uses_cache_when_present(ft_creds, monkeypatch):
    # First call writes to cache; second call must not hit requests.post again.
    monkeypatch.setattr(
        ft_auth.requests, "post",
        lambda *a, **k: FakeResponse(json_data={"access_token": "cached-tok"}),
    )
    first = ft_auth.france_travail_token(timeout=5, use_cache=True, cache_ttl_hours=1.0)
    assert first == "cached-tok"

    def _explode(*a, **k):
        raise AssertionError("should have used cache")

    monkeypatch.setattr(ft_auth.requests, "post", _explode)
    second = ft_auth.france_travail_token(timeout=5, use_cache=True, cache_ttl_hours=1.0)
    assert second == "cached-tok"


def test_invalidate_token_cache_removes_file(ft_creds, monkeypatch):
    monkeypatch.setattr(
        ft_auth.requests, "post",
        lambda *a, **k: FakeResponse(json_data={"access_token": "to-clear"}),
    )
    ft_auth.france_travail_token(timeout=5, use_cache=True, cache_ttl_hours=1.0)
    # Now invalidate — next cached read should miss and call post again.
    ft_auth.invalidate_france_travail_token_cache()
    calls = {"n": 0}

    def _post(*a, **k):
        calls["n"] += 1
        return FakeResponse(json_data={"access_token": "fresh"})

    monkeypatch.setattr(ft_auth.requests, "post", _post)
    token = ft_auth.france_travail_token(timeout=5, use_cache=True, cache_ttl_hours=1.0)
    assert token == "fresh"
    assert calls["n"] == 1


def test_scope_candidates_dedupes_and_includes_configured(monkeypatch):
    monkeypatch.setenv("FRANCE_TRAVAIL_SCOPE", "custom_scope api_x")
    scopes = ft_auth._scope_candidates("client-9")
    assert scopes[0] == "custom_scope api_x"
    assert len(scopes) == len(set(scopes))


# ── endpoints registry ───────────────────────────────────────────────────────

def test_registry_returns_defaults_without_override(monkeypatch, tmp_path):
    monkeypatch.delenv("FRANCE_TRAVAIL_ENDPOINTS_FILE", raising=False)
    monkeypatch.chdir(tmp_path)  # no .france_travail.endpoints.local.json here
    registry = ft_ep.load_endpoint_registry()
    assert registry["job_offers"].enabled is True
    assert registry["anotea"].enabled is False


def test_registry_applies_local_override(monkeypatch, tmp_path):
    override = tmp_path / "endpoints.json"
    override.write_text(json.dumps({
        "base_url": "https://override.example",
        "endpoints": {
            "anotea": {"path": "/anotea/v1", "rate_per_sec": 4, "method": "post", "params": {"x": "1"}},
        },
    }), encoding="utf-8")
    monkeypatch.setenv("FRANCE_TRAVAIL_ENDPOINTS_FILE", str(override))
    registry = ft_ep.load_endpoint_registry()
    assert registry["anotea"].enabled is True  # path present -> enabled
    assert registry["anotea"].path == "/anotea/v1"
    assert registry["anotea"].method == "POST"
    assert registry["anotea"].params == {"x": "1"}
    assert ft_ep.load_endpoint_base_url() == "https://override.example"


def test_registry_ignores_malformed_override(monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("FRANCE_TRAVAIL_ENDPOINTS_FILE", str(bad))
    registry = ft_ep.load_endpoint_registry()
    assert registry["job_offers"].enabled is True
    # base url falls back to default when file unparseable
    assert ft_ep.load_endpoint_base_url() == "https://api.francetravail.io"


# ── client request mapping ───────────────────────────────────────────────────

def test_client_rejects_disabled_endpoint(ft_creds, monkeypatch, tmp_path):
    monkeypatch.delenv("FRANCE_TRAVAIL_ENDPOINTS_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    client = ft_client.FranceTravailClient(ft_client.ClientConfig(use_cache=False))
    with pytest.raises(ValueError, match="is not configured"):
        client.request("anotea")


def test_client_get_request_returns_payload(ft_creds, monkeypatch, tmp_path):
    monkeypatch.delenv("FRANCE_TRAVAIL_ENDPOINTS_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ft_client, "france_travail_token", lambda **k: "tok-1")
    captured = {}

    def _get(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return FakeResponse(json_data={"resultats": [{"id": "1"}]})

    monkeypatch.setattr(ft_client.requests, "get", _get)
    client = ft_client.FranceTravailClient(ft_client.ClientConfig(use_cache=False))
    payload = client.request("job_offers", params={"motsCles": "data"})
    assert payload == {"resultats": [{"id": "1"}]}
    assert "/partenaire/offresdemploi/v2/offres/search" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer tok-1"


def test_client_post_request_uses_post(ft_creds, monkeypatch, tmp_path):
    override = tmp_path / "ep.json"
    override.write_text(json.dumps({
        "endpoints": {"romeo": {"path": "/romeo/v1", "method": "POST", "rate_per_sec": 0}},
    }), encoding="utf-8")
    monkeypatch.setenv("FRANCE_TRAVAIL_ENDPOINTS_FILE", str(override))
    monkeypatch.setattr(ft_client, "france_travail_token", lambda **k: "tok-2")
    used = {"post": False}

    def _post(url, **kwargs):
        used["post"] = True
        return FakeResponse(json_data={"ok": True})

    monkeypatch.setattr(ft_client.requests, "post", _post)
    client = ft_client.FranceTravailClient(ft_client.ClientConfig(use_cache=False))
    payload = client.request("romeo", json_body={"q": "x"})
    assert payload == {"ok": True}
    assert used["post"] is True


def test_client_retries_once_on_401_with_cache_bypassed_token(ft_creds, monkeypatch, tmp_path):
    monkeypatch.delenv("FRANCE_TRAVAIL_ENDPOINTS_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

    minted: list[bool] = []

    def _token(**kwargs):
        minted.append(bool(kwargs.get("use_cache")))
        return "stale-tok" if len(minted) == 1 else "fresh-tok"

    monkeypatch.setattr(ft_client, "france_travail_token", _token)
    invalidated = {"n": 0}
    monkeypatch.setattr(
        ft_client, "invalidate_france_travail_token_cache",
        lambda: invalidated.__setitem__("n", invalidated["n"] + 1),
    )

    calls = {"n": 0}

    def _get(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse(status_code=401, json_data={"error": "unauthorized"})
        return FakeResponse(json_data={"resultats": []})

    monkeypatch.setattr(ft_client.requests, "get", _get)
    client = ft_client.FranceTravailClient(ft_client.ClientConfig(use_cache=True))
    payload = client.request("job_offers", params={"motsCles": "data"})

    assert payload == {"resultats": []}
    assert calls["n"] == 2            # original 401 + one retry
    assert invalidated["n"] == 1      # token cache cleared before retry
    assert minted == [True, False]    # retry mints with the cache bypassed


# ── rate limiter ─────────────────────────────────────────────────────────────

def test_rate_limiter_no_wait_when_rate_zero():
    limiter = ft_client.RateLimiter()
    # Should return immediately and not raise for rate 0.
    limiter.wait("k", 0)
    assert "k" not in limiter._next_allowed


# ── la bonne alternance ──────────────────────────────────────────────────────

def test_lba_token_missing_raises(monkeypatch):
    monkeypatch.setattr(lba, "load_local_env", lambda: None)
    monkeypatch.delenv("APPRENTISSAGE_API_TOKEN", raising=False)
    monkeypatch.delenv("LABONNEALTERNANCE_API_TOKEN", raising=False)
    with pytest.raises(lba.FreeApiError, match="APPRENTISSAGE_API_TOKEN"):
        lba._lba_token()


def test_lba_departements_mapping():
    assert lba._lba_departements("Paris") == ["75"]
    assert lba._lba_departements("ile-de-france") == lba._LBA_IDF_DEPARTMENTS
    assert lba._lba_departements("92") == ["92"]
    assert lba._lba_departements("France") == []
    assert lba._lba_departements("Berlin") == []


def test_lba_romes_expands_query():
    romes = lba._lba_romes("data scientist")
    assert "M1403" in romes
    assert len(romes) <= 6


def test_lba_fetch_maps_jobs(monkeypatch):
    monkeypatch.setattr(lba, "load_local_env", lambda: None)
    monkeypatch.setenv("APPRENTISSAGE_API_TOKEN", "lba-tok")
    payload = {
        "jobs": [
            {
                "identifier": {"id": "abc"},
                "offer": {
                    "title": "Data Scientist Alternance",
                    "description": "Build ML pipelines in Python.",
                    "desired_skills": ["python", "sql"],
                    "to_be_acquired_skills": ["mlops"],
                    "rome_codes": ["M1403"],
                    "publication": {"creation": "2026-01-01"},
                },
                "workplace": {"name": "Acme", "location": {"address": "Paris 75"}},
                "contract": {"type": ["Alternance"], "remote": "false"},
                "apply": {"url": "https://lba.example/apply/abc"},
            }
        ]
    }
    monkeypatch.setattr(lba, "_fetch_json", lambda *a, **k: payload)
    search = FreeApiSearch(source="labonnealternance", query="data scientist", location="Paris")
    jobs = lba.fetch(search)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Data Scientist Alternance"
    assert job.company == "Acme"
    assert job.apply_url == "https://lba.example/apply/abc"
    assert "python" in job.tech_stack


def test_lba_fetch_dedupes_and_handles_empty(monkeypatch):
    monkeypatch.setattr(lba, "load_local_env", lambda: None)
    monkeypatch.setenv("APPRENTISSAGE_API_TOKEN", "lba-tok")
    monkeypatch.setattr(lba, "_fetch_json", lambda *a, **k: {"jobs": []})
    search = FreeApiSearch(source="labonnealternance", query="data", location="Paris")
    assert lba.fetch(search) == []
