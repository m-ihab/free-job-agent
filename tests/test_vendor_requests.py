"""Behavioural tests for the vendored ``requests`` fallback shim.

Monkeypatches ``urllib.request.urlopen`` so no real network happens, and asserts
that http(s) requests work, that non-http(s) schemes (file://, ftp://) are
rejected as defense-in-depth, and that the get/post/json/raise_for_status
helpers behave as documented.
"""
from __future__ import annotations

import io
from urllib import error

import pytest

from job_agent._vendor import requests as shim


class _FakeHTTPResponse:
    """Mimics the context-manager object returned by urllib.urlopen."""

    def __init__(self, body: bytes, status: int = 200, headers=None):
        self._body = body
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


@pytest.fixture
def fake_urlopen(monkeypatch):
    captured = {}

    def _factory(body=b'{"ok": true}', status=200, headers=None):
        def _urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["data"] = req.data
            captured["timeout"] = timeout
            captured["headers"] = dict(req.header_items())
            return _FakeHTTPResponse(body, status, headers)

        monkeypatch.setattr(shim.request, "urlopen", _urlopen)
        return captured

    return _factory


# ── scheme guard ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/resource",
    "gopher://example.com",
])
def test_non_http_schemes_rejected(url):
    with pytest.raises(shim.ConnectionError, match="non-http"):
        shim.get(url)


# ── GET ──────────────────────────────────────────────────────────────────────

def test_get_returns_response_with_json(fake_urlopen):
    fake_urlopen(body=b'{"hello": "world"}')
    resp = shim.get("https://example.com/api")
    assert resp.status_code == 200
    assert resp.json() == {"hello": "world"}


def test_get_appends_query_params(fake_urlopen):
    captured = fake_urlopen()
    shim.get("https://example.com/api", params={"q": "data", "n": 5, "skip": None})
    assert "q=data" in captured["url"]
    assert "n=5" in captured["url"]
    # None-valued params are dropped.
    assert "skip" not in captured["url"]


def test_get_sends_custom_headers(fake_urlopen):
    captured = fake_urlopen()
    shim.get("https://example.com/api", headers={"Authorization": "Bearer t"})
    # urllib normalizes header keys to title-case.
    assert captured["headers"].get("Authorization") == "Bearer t"


# ── POST ─────────────────────────────────────────────────────────────────────

def test_post_form_encodes_dict_body(fake_urlopen):
    captured = fake_urlopen()
    shim.post("https://example.com/token", data={"grant_type": "client_credentials"})
    assert captured["method"] == "POST"
    assert b"grant_type=client_credentials" in captured["data"]


def test_post_string_body_is_encoded(fake_urlopen):
    captured = fake_urlopen()
    shim.post("https://example.com/raw", data="plain-text-body")
    assert captured["data"] == b"plain-text-body"


# ── Response helpers ─────────────────────────────────────────────────────────

def test_response_text_uses_charset_from_content_type():
    resp = shim.Response(
        url="https://x",
        status_code=200,
        headers={"Content-Type": "text/plain; charset=latin-1"},
        content="café".encode("latin-1"),
    )
    assert resp.text == "café"


def test_raise_for_status_raises_on_4xx():
    resp = shim.Response(url="https://x", status_code=404, headers={}, content=b"")
    with pytest.raises(shim.HTTPError):
        resp.raise_for_status()


def test_raise_for_status_silent_on_2xx():
    resp = shim.Response(url="https://x", status_code=204, headers={}, content=b"")
    assert resp.raise_for_status() is None


# ── error translation ────────────────────────────────────────────────────────

def test_http_error_returns_response_not_raise(monkeypatch):
    def _urlopen(req, timeout=None):
        raise error.HTTPError(req.full_url, 500, "Server Error", hdrs=None, fp=io.BytesIO(b"boom"))

    monkeypatch.setattr(shim.request, "urlopen", _urlopen)
    resp = shim.get("https://example.com/fail")
    assert resp.status_code == 500
    assert resp.content == b"boom"


def test_timeout_url_error_becomes_timeout(monkeypatch):
    def _urlopen(req, timeout=None):
        raise error.URLError("the read operation timed out")

    monkeypatch.setattr(shim.request, "urlopen", _urlopen)
    with pytest.raises(shim.Timeout):
        shim.get("https://example.com/slow")


def test_generic_url_error_becomes_connection_error(monkeypatch):
    def _urlopen(req, timeout=None):
        raise error.URLError("name resolution failed")

    monkeypatch.setattr(shim.request, "urlopen", _urlopen)
    with pytest.raises(shim.ConnectionError):
        shim.get("https://example.com/down")
