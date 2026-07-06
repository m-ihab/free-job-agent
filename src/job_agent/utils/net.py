"""Safe outbound HTTP for user-supplied URLs (SSRF defense).

Job/feed intake fetches URLs the user (or a cross-origin page, before the
dashboard CSRF guard) can influence. Without a guard those fetches can reach
internal services, cloud metadata (169.254.169.254), or — via the vendored
``requests`` shim's ``urllib`` backend — ``file://`` for local file disclosure.

``validate_public_http_url`` enforces an http(s) scheme and blocks hosts that
resolve to private/loopback/link-local/reserved ranges. ``safe_get`` additionally
re-validates every redirect hop, pins the connection to the vetted IP (closing
the validate→connect DNS-rebinding window) and caps the response size.
"""
from __future__ import annotations

import contextlib
import ipaddress
import logging
import socket
import threading
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
DEFAULT_MAX_BYTES = 8_000_000

# ── Thread-safe connect-time pinning ──────────────────────────────────────────
# We resolve+validate a host, then must make the actual socket connect to that
# *same* vetted IP (else a DNS-rebinding host could flip to a private address
# between validate and connect). Rather than swapping ``socket.getaddrinfo``
# process-wide per call (which races across the dashboard's worker threads), we
# install a single resolver shim once and drive it from THREAD-LOCAL pins, so
# concurrent fetches never clobber each other's pin.
_real_getaddrinfo = socket.getaddrinfo
_pins = threading.local()


def _pinned_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    pins: dict[str, str] = getattr(_pins, "map", None) or {}
    target = pins.get(host, host)
    return _real_getaddrinfo(target, *args, **kwargs)


# Install once (idempotent across re-imports).
if socket.getaddrinfo is not _pinned_getaddrinfo:  # pragma: no branch
    socket.getaddrinfo = _pinned_getaddrinfo  # type: ignore[assignment]


class UnsafeUrlError(ValueError):
    """Raised when a URL is unsafe to fetch (bad scheme or non-public host)."""


def _blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # An IPv4-mapped IPv6 address (``::ffff:127.0.0.1``) does NOT report
    # is_private/is_loopback on the IPv6 object, so unwrap it to its IPv4 form
    # before classifying — otherwise it slips past the block list.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
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


def _validate(url: str) -> tuple[str, ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Validate scheme + host and return ``(host, vetted_ip)``.

    The returned IP is one we have confirmed public; pinning the connection to
    it (see :func:`_pin_host`) closes the DNS-rebinding window between validation
    and connect.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"URL scheme '{scheme or '(none)'}' is not allowed; use http or https.")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL has no host.")
    ips = _resolve(host)
    for ip in ips:
        if _blocked(ip):
            raise UnsafeUrlError(f"URL host '{host}' resolves to a non-public address ({ip}).")
    return host, ips[0]


def validate_public_http_url(url: str) -> str:
    """Return ``url`` unchanged if it is an http(s) URL whose host resolves only
    to public addresses; otherwise raise :class:`UnsafeUrlError`."""
    _validate(url)
    return url


@contextlib.contextmanager
def _pin_host(host: str, ip: str) -> Iterator[None]:
    """Pin ``host`` to the already-vetted ``ip`` for the duration of a single
    fetch on THIS thread, so the socket connects to the address we validated
    rather than re-resolving (which a rebinding attacker could flip to a private
    IP). State is thread-local, so concurrent fetches don't interfere."""
    pins: dict[str, str] | None = getattr(_pins, "map", None)
    if pins is None:
        pins = {}
        _pins.map = pins
    had = host in pins
    previous = pins.get(host)
    pins[host] = ip
    try:
        yield
    finally:
        if had:
            pins[host] = previous  # type: ignore[assignment]
        else:
            pins.pop(host, None)


def _enforce_size(resp: Any, max_bytes: int) -> None:
    """Cap the response body without materializing an oversized one.

    Order matters for the memory-DoS case: reject on the declared
    Content-Length first, then (real requests, stream=True) read in chunks and
    abort mid-download the moment the counter passes the cap. Only clients
    without ``iter_content`` (the vendored stdlib shim) fall back to checking
    the already-materialized body.
    """
    declared = (getattr(resp, "headers", {}) or {}).get("Content-Length")
    if declared:
        try:
            declared_size = int(declared)
        except (TypeError, ValueError):
            declared_size = None  # malformed header — rely on the byte-counted read
        if declared_size is not None and declared_size > max_bytes:
            raise UnsafeUrlError(f"Response exceeds the {max_bytes}-byte limit.")
    iter_content = getattr(resp, "iter_content", None)
    if callable(iter_content):
        total = 0
        chunks: list[bytes] = []
        for chunk in iter_content(65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                try:
                    resp.close()
                except Exception:
                    logger.debug("Response close after size-cap abort failed", exc_info=True)
                raise UnsafeUrlError(f"Response exceeds the {max_bytes}-byte limit.")
            chunks.append(chunk)
        # Hand the fully-read, capped body back through the normal .content
        # attribute so callers are agnostic to the streaming read.
        resp._content = b"".join(chunks)
        return
    content = getattr(resp, "content", b"") or b""
    if len(content) > max_bytes:
        raise UnsafeUrlError(f"Response exceeds the {max_bytes}-byte limit.")


def _get_without_redirects(requests: Any, url: str, headers: dict[str, str] | None,
                           timeout: int | float) -> tuple[Any, bool]:
    """GET with auto-redirects disabled, streaming when the client supports it.

    Returns ``(response, manual_redirects_supported)``. The second element is
    False only for odd clients lacking ``allow_redirects`` entirely.
    """
    try:
        return requests.get(url, headers=headers, timeout=timeout,
                            allow_redirects=False, stream=True), True
    except TypeError:
        pass  # client without stream support (e.g. the vendored shim)
    try:
        return requests.get(url, headers=headers, timeout=timeout,
                            allow_redirects=False), True
    except TypeError:
        return requests.get(url, headers=headers, timeout=timeout), False


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

    current = url
    hops = 0
    while True:
        host, ip = _validate(current)
        # ``_pin_host`` makes the connect use the IP we just vetted, closing
        # the validate→connect rebinding window. Redirects are followed
        # manually so each hop is re-validated; streaming (when the client
        # supports it) lets the size cap abort mid-download.
        with _pin_host(host, str(ip)):
            resp, manual_redirects = _get_without_redirects(requests, current, headers, timeout)
        if not manual_redirects:
            # A non-conforming client without ``allow_redirects`` (odd test
            # doubles only) cannot drive per-hop revalidation, so refuse to
            # hand back a redirect rather than risk an unvalidated follow.
            if (getattr(resp, "status_code", 0) in _REDIRECT_CODES
                    and (getattr(resp, "headers", {}) or {}).get("Location")):
                raise UnsafeUrlError("Redirect cannot be revalidated on this client.")
            _enforce_size(resp, max_bytes)
            return resp
        location = (getattr(resp, "headers", {}) or {}).get("Location")
        if getattr(resp, "status_code", 0) in _REDIRECT_CODES and location:
            try:
                resp.close()
            except Exception:
                logger.debug("Closing redirect response failed", exc_info=True)
            hops += 1
            if hops > max_redirects:
                raise UnsafeUrlError("Too many redirects.")
            current = urljoin(current, location)
            continue
        _enforce_size(resp, max_bytes)
        return resp
