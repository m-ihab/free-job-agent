"""The vendored requests fallback must refuse non-http(s) schemes (file://, ftp://).

The shim now lives under job_agent._vendor and is only used when the real
``requests`` package is absent; we test it directly rather than relying on
import shadowing.
"""
from __future__ import annotations

import pytest

from job_agent._vendor import requests as shim


def test_shim_exposes_request_surface() -> None:
    assert hasattr(shim, "_request") and hasattr(shim, "get")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "file:///C:/Windows/win.ini", "ftp://x/y"])
def test_shim_rejects_non_http_schemes(url: str) -> None:
    with pytest.raises(shim.ConnectionError):
        shim.get(url, timeout=1)


def test_real_requests_is_used_when_installed() -> None:
    # With the real package installed, `import requests` must NOT resolve to the
    # vendored fallback (fidelity: tests exercise the same client as production).
    import requests

    assert not hasattr(requests, "_request"), "vendored shim is shadowing the real requests"
