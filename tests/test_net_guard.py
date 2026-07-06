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
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped IPv6 loopback
        "http://[::ffff:10.0.0.1]/",   # IPv4-mapped IPv6 private
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


def test_safe_get_rejects_oversized_declared_content_length(monkeypatch: pytest.MonkeyPatch) -> None:
    """A multi-GB Content-Length must be rejected before any body is read."""
    monkeypatch.setattr(
        "job_agent.utils.net.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    fake = _Resp(200, {"Content-Length": str(5_000_000_000)}, content=b"tiny")
    monkeypatch.setattr("requests.get", lambda *a, **k: fake)
    with pytest.raises(UnsafeUrlError):
        safe_get("https://example.com/jobs")


def test_safe_get_streaming_read_aborts_past_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a streaming client, the byte counter must abort the download the
    moment it passes max_bytes — the full body is never materialized."""
    monkeypatch.setattr(
        "job_agent.utils.net.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )

    class _StreamResp(_Resp):
        def __init__(self) -> None:
            super().__init__(200, {})
            self.closed = False

        def iter_content(self, _size: int):
            while True:  # endless body — must be cut off by the cap
                yield b"x" * 1024

        def close(self) -> None:
            self.closed = True

    fake = _StreamResp()
    monkeypatch.setattr("requests.get", lambda *a, **k: fake)
    with pytest.raises(UnsafeUrlError):
        safe_get("https://example.com/jobs", max_bytes=10_000)
    assert fake.closed


def test_safe_get_streaming_body_within_cap_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "job_agent.utils.net.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )

    class _StreamResp(_Resp):
        def iter_content(self, _size: int):
            yield b"<html>"
            yield b"job</html>"

        @property
        def content(self) -> bytes:
            return self._content

        @content.setter
        def content(self, value: bytes) -> None:
            self._content = value

    fake = _StreamResp(200, {})
    monkeypatch.setattr("requests.get", lambda *a, **k: fake)
    resp = safe_get("https://example.com/jobs")
    assert resp.content == b"<html>job</html>"


def test_pin_host_forces_resolution_and_restores(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_pin_host`` makes the connect use the vetted IP (no rebinding re-resolve)
    via a thread-local pin, leaving resolution untouched afterwards."""
    import job_agent.utils.net as net

    # Underlying resolver echoes the requested host back as its "address"; the
    # installed shim must be the active resolver for the pin to take effect.
    monkeypatch.setattr(net, "_real_getaddrinfo", lambda h, *a, **k: [(2, 1, 6, "", (h, 0))])
    monkeypatch.setattr(net.socket, "getaddrinfo", net._pinned_getaddrinfo)

    with net._pin_host("evil.example.com", "93.184.216.34"):
        pinned = net.socket.getaddrinfo("evil.example.com", 80)[0][4][0]
        untouched = net.socket.getaddrinfo("other.example.com", 80)[0][4][0]
        assert pinned == "93.184.216.34"      # forced to the vetted IP
        assert untouched == "other.example.com"  # other hosts unaffected

    # Pin cleared after the context exits.
    assert net.socket.getaddrinfo("evil.example.com", 80)[0][4][0] == "evil.example.com"


def test_pin_host_is_thread_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent pins on different threads must not clobber each other — one
    thread pinning ``host`` must not leak into another thread's resolution."""
    import threading

    import job_agent.utils.net as net

    monkeypatch.setattr(net, "_real_getaddrinfo", lambda h, *a, **k: [(2, 1, 6, "", (h, 0))])
    monkeypatch.setattr(net.socket, "getaddrinfo", net._pinned_getaddrinfo)

    seen: dict[str, str] = {}
    barrier = threading.Barrier(2)

    def worker(name: str, ip: str) -> None:
        with net._pin_host("shared.example.com", ip):
            barrier.wait()  # both threads hold a pin at the same time
            seen[name] = net.socket.getaddrinfo("shared.example.com", 80)[0][4][0]

    threads = [
        threading.Thread(target=worker, args=("a", "1.1.1.1")),
        threading.Thread(target=worker, args=("b", "2.2.2.2")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert seen == {"a": "1.1.1.1", "b": "2.2.2.2"}  # no cross-thread bleed


def test_safe_get_fallback_refuses_unrevalidated_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    """A client that cannot honour allow_redirects must not be allowed to hand
    back a redirect we never revalidated."""
    monkeypatch.setattr(
        "job_agent.utils.net.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )

    def strict_get(url: str, headers=None, timeout=None) -> _Resp:  # no allow_redirects kwarg
        return _Resp(302, {"Location": "http://169.254.169.254/"})

    monkeypatch.setattr("requests.get", strict_get)
    with pytest.raises(UnsafeUrlError):
        safe_get("https://example.com/jobs")


def test_safe_get_passes_allow_redirects_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """safe_get must follow redirects manually (allow_redirects=False) so every
    hop is re-validated — never delegate redirect following to the client."""
    monkeypatch.setattr(
        "job_agent.utils.net.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    seen: dict = {}

    def fake_get(url: str, **kwargs: object) -> _Resp:
        seen.update(kwargs)
        return _Resp(200, {}, content=b"ok")

    monkeypatch.setattr("requests.get", fake_get)
    safe_get("https://example.com/jobs")
    assert seen.get("allow_redirects") is False
