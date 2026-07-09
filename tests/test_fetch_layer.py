"""Tests for the adaptive fetch layer (Scrapling optional, requests fallback)."""
from __future__ import annotations

import job_agent.intake.fetch_layer as fl


class _FakePage:
    status = 200
    html_content = "<html>jobs</html>"


class _FakeFetcher:
    @staticmethod
    def get(url, timeout=None):
        return _FakePage()


class _FakeResponse:
    status_code = 200
    text = "<html>fallback</html>"


def test_scrapling_backend_used_when_available(monkeypatch):
    monkeypatch.setattr(fl, "_load_scrapling", lambda: _FakeFetcher)
    result = fl.fetch_static("https://example.org/careers")
    assert result.backend == "scrapling"
    assert result.ok
    assert result.text == "<html>jobs</html>"


def test_requests_fallback_when_scrapling_missing(monkeypatch):
    import job_agent.utils.net as net

    monkeypatch.setattr(fl, "_load_scrapling", lambda: None)
    monkeypatch.setattr(net, "safe_get", lambda url, headers=None, timeout=None: _FakeResponse())
    result = fl.fetch_static("https://example.org/careers")
    assert result.backend == "requests"
    assert result.ok
    assert result.text == "<html>fallback</html>"


def test_requests_fallback_when_scrapling_raises(monkeypatch):
    import job_agent.utils.net as net

    class _Broken:
        @staticmethod
        def get(url, timeout=None):
            raise RuntimeError("scrapling exploded")

    monkeypatch.setattr(fl, "_load_scrapling", lambda: _Broken)
    monkeypatch.setattr(net, "safe_get", lambda url, headers=None, timeout=None: _FakeResponse())
    result = fl.fetch_static("https://example.org/careers")
    assert result.backend == "requests"
    assert result.ok


def test_never_raises_on_total_failure(monkeypatch):
    import job_agent.utils.net as net

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(fl, "_load_scrapling", lambda: None)
    monkeypatch.setattr(net, "safe_get", _boom)
    result = fl.fetch_static("https://example.org/careers")
    assert result.backend == "error"
    assert not result.ok
    assert result.status_code == 0


def test_bytes_body_is_decoded(monkeypatch):
    class _BytesPage:
        status_code = 200
        html_content = None
        body = b"<html>bytes</html>"

    class _BytesFetcher:
        @staticmethod
        def get(url, timeout=None):
            return _BytesPage()

    monkeypatch.setattr(fl, "_load_scrapling", lambda: _BytesFetcher)
    result = fl.fetch_static("https://example.org")
    assert result.text == "<html>bytes</html>"
    assert result.backend == "scrapling"


def test_ok_requires_2xx_3xx_and_body():
    assert not fl.FetchResult("u", 404, "page", "requests").ok
    assert not fl.FetchResult("u", 200, "", "requests").ok
    assert fl.FetchResult("u", 200, "x", "requests").ok
