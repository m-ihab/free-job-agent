"""Request guard for the local dashboard (anti-CSRF / anti-DNS-rebinding).

The dashboard binds loopback, but any website the user visits can issue requests
to 127.0.0.1, and ~40 POST routes drive real actions (auto-apply, URL fetch, job
deletion). This guard requires, for every state-changing request, that the
``Origin``/``Referer`` is same-origin AND a per-process session token is present.
It also validates the ``Host`` header against an allowlist to defeat DNS
rebinding. The token is minted once per process and injected into the served
``index.html`` (same-origin HTML a cross-origin page cannot read).
"""
from __future__ import annotations

import ipaddress
import secrets
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

SESSION_TOKEN = secrets.token_urlsafe(32)
TOKEN_HEADER = "X-Job-Agent-Token"
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().strip("[]").lower()
    if h in ("", "localhost"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _allowed_authorities(bound_host: str, bound_port: int) -> set[str]:
    auth = {
        f"127.0.0.1:{bound_port}",
        f"localhost:{bound_port}",
        f"[::1]:{bound_port}",
        f"{bound_host}:{bound_port}",
    }
    return {a.lower() for a in auth}


def _header_host(handler: BaseHTTPRequestHandler) -> str:
    return (handler.headers.get("Host") or "").strip().lower()


def _origin_authority(handler: BaseHTTPRequestHandler) -> str | None:
    raw = handler.headers.get("Origin") or handler.headers.get("Referer")
    if not raw:
        return None
    return (urlparse(raw).netloc or "").lower() or None


def check_request(
    handler: BaseHTTPRequestHandler,
    method: str,
    *,
    bound_host: str,
    bound_port: int,
    token: str = SESSION_TOKEN,
) -> tuple[bool, str]:
    """Return ``(allowed, reason)``.

    Host allowlist is enforced only when bound to loopback (the default); a
    deliberate non-loopback bind can't know the client's intended Host, so it
    relies on the token. Mutating methods always require same-origin + token.
    """
    allowed = _allowed_authorities(bound_host, bound_port)
    host = _header_host(handler)
    if is_loopback_host(bound_host) and host and host not in allowed:
        return False, "host-not-allowed"
    if method.upper() not in MUTATING_METHODS:
        return True, ""
    origin = _origin_authority(handler)
    if origin is not None and origin not in allowed:
        return False, "cross-origin"
    supplied = handler.headers.get(TOKEN_HEADER) or ""
    if not supplied or not secrets.compare_digest(supplied, token):
        return False, "missing-or-invalid-token"
    return True, ""
