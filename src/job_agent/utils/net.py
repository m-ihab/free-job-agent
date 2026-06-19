"""Safe outbound HTTP for user-supplied URLs (SSRF defense).

Job/feed intake fetches URLs the user (or a cross-origin page, before the
dashboard CSRF guard) can influence. Without a guard those fetches can reach
internal services, cloud metadata (169.254.169.254), or — via the vendored
``requests`` shim's ``urllib`` backend — ``file://`` for local file disclosure.

``validate_public_http_url`` enforces an http(s) scheme and blocks hosts that
resolve to private/loopback/link-local/reserved ranges. ``safe_get`` additionally
re-validates every redirect hop and caps the response size.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

ALLOWED_SCHEMES = frozenset({"http", "https"})
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
DEFAULT_MAX_BYTES = 8_000_000


class UnsafeUrlError(ValueError):
    """Raised when a URL is unsafe to fetch (bad scheme or non-public host)."""


def _blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not resolve host '{host}'.") from exc
    out: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        addr = str(info[4][0]).split("%", 1)[0]  # strip IPv6 scope id
        try:
            out.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    if not out:
        raise UnsafeUrlError(f"Could not resolve host '{host}'.")
    return out


def validate_public_http_url(url: str) -> str:
    """Return ``url`` unchanged if it is an http(s) URL whose host resolves only
    to public addresses; otherwise raise :class:`UnsafeUrlError`."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"URL scheme '{scheme or '(none)'}' is not allowed; use http or https.")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL has no host.")
    for ip in _resolve(host):
        if _blocked(ip):
            raise UnsafeUrlError(f"URL host '{host}' resolves to a non-public address ({ip}).")
    return url


def _enforce_size(resp: Any, max_bytes: int) -> None:
    content = getattr(resp, "content", b"") or b""
    if len(content) > max_bytes:
        raise UnsafeUrlError(f"Response exceeds the {max_bytes}-byte limit.")


def safe_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int | float = 15,
    max_redirects: int = 5,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Any:
    """SSRF-safe ``requests.get``: validates the URL and every redirect target,
    follows redirects manually so each hop is re-checked, and caps body size."""
    import requests  # real package when installed, else job_agent vendored shim

    validate_public_http_url(url)
    current = url
    hops = 0
    while True:
        try:
            # allow_redirects exists on the real requests; the vendored shim
            # lacks it and raises TypeError, handled below.
            resp = requests.get(current, headers=headers, timeout=timeout, allow_redirects=False)  # type: ignore[call-arg]
        except TypeError:
            # Vendored shim lacks ``allow_redirects``; it follows internally but
            # independently refuses non-http(s) schemes, so file:// stays blocked.
            resp = requests.get(current, headers=headers, timeout=timeout)
            _enforce_size(resp, max_bytes)
            return resp
        location = (getattr(resp, "headers", {}) or {}).get("Location")
        if getattr(resp, "status_code", 0) in _REDIRECT_CODES and location:
            hops += 1
            if hops > max_redirects:
                raise UnsafeUrlError("Too many redirects.")
            current = urljoin(current, location)
            validate_public_http_url(current)
            continue
        _enforce_size(resp, max_bytes)
        return resp
