"""Small local subset of the ``requests`` API used by this project.

This fallback keeps the project usable in locked-down environments where the
third-party ``requests`` package is unavailable. It intentionally implements
only the small surface area the app and tests rely on.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


class RequestException(Exception):
    """Base HTTP client error."""


class HTTPError(RequestException):
    """Raised for non-2xx HTTP status codes."""


class Timeout(RequestException):
    """Raised when a request times out."""


class ConnectionError(RequestException):
    """Raised when the remote endpoint cannot be reached."""


class exceptions:
    RequestException = RequestException
    HTTPError = HTTPError
    Timeout = Timeout
    ConnectionError = ConnectionError


@dataclass
class Response:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str:
        charset = "utf-8"
        content_type = self.headers.get("Content-Type", "")
        if "charset=" in content_type:
            charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"{self.status_code} for {self.url}")


def _build_url(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    query = parse.urlencode(
        [(key, value) for key, value in params.items() if value is not None],
        doseq=True,
    )
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{query}"


def _coerce_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    return {str(k): str(v) for k, v in (headers or {}).items()}


def _request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | bytes | str | None = None,
    headers: dict[str, Any] | None = None,
    timeout: int | float | None = None,
) -> Response:
    final_url = _build_url(url, params)
    scheme = parse.urlsplit(final_url).scheme.lower()
    if scheme not in ("http", "https"):
        # Defense-in-depth: urllib would otherwise honor file://, ftp://, etc.,
        # turning a fetched URL into a local-file/SSRF read.
        raise ConnectionError(f"Refusing to fetch non-http(s) URL (scheme={scheme or 'none'}).")
    payload: bytes | None = None
    req_headers = _coerce_headers(headers)
    if isinstance(data, dict):
        payload = parse.urlencode(data).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif isinstance(data, str):
        payload = data.encode("utf-8")
    else:
        payload = data

    req = request.Request(final_url, data=payload, headers=req_headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=timeout or 20) as resp:
            raw = resp.read()
            resp_headers = {k: v for k, v in resp.headers.items()}
            return Response(final_url, int(getattr(resp, "status", 200)), resp_headers, raw)
    except error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        resp_headers = {k: v for k, v in exc.headers.items()} if exc.headers else {}
        return Response(final_url, exc.code, resp_headers, raw)
    except error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if "timed out" in str(reason).lower():
            raise Timeout(str(reason)) from exc
        raise ConnectionError(str(reason)) from exc


def get(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
    timeout: int | float | None = None,
) -> Response:
    return _request("GET", url, params=params, headers=headers, timeout=timeout)


def post(
    url: str,
    data: dict[str, Any] | bytes | str | None = None,
    headers: dict[str, Any] | None = None,
    timeout: int | float | None = None,
) -> Response:
    return _request("POST", url, data=data, headers=headers, timeout=timeout)
