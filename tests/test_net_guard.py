"""SSRF guard: scheme allowlist, private-IP blocking, redirect re-validation."""
from __future__ import annotations

import pytest

from job_agent.utils.net import UnsafeUrlError, safe_get, validate_public_http_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/win.ini",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com",
        "http://127.0.0.1/admin",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://0.0.0.0/",
    ],
)
def test_unsafe_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_http_url(url)


def test_public_url_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Avoid real DNS: example.com resolves to a public address.
    monkeypatch.setattr(
        "job_agent.utils.net.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    assert validate_public_http_url("https://example.com/jobs") == "https://example.com/jobs"


def test_url_with_no_host_is_rejected() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_http_url("http:///nohost")


class _Resp:
    def __init__(self, status_code: int, headers: dict, content: bytes = b"") -> None:
        self.status_code = status_code
        self.headers = headers
        self.content = content


def test_safe_get_revalidates_redirect_to_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "job_agent.utils.net.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    # First (and only) hop is a redirect pointing at the cloud-metadata IP.
    fake = _Resp(302, {"Location": "http://169.254.169.254/latest/"})
    monkeypatch.setattr("requests.get", lambda *a, **k: fake)
    with pytest.raises(UnsafeUrlError):
        safe_get("https://example.com/jobs")


def test_safe_get_returns_final_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "job_agent.utils.net.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    ok = _Resp(200, {}, content=b"<html>job</html>")
    monkeypatch.setattr("requests.get", lambda *a, **k: ok)
    resp = safe_get("https://example.com/jobs")
    assert resp.status_code == 200
