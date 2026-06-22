"""GET handlers for portfolio routes (read, preview, css, assets, export)."""
from __future__ import annotations

from http import HTTPStatus
from pathlib import Path

from job_agent.portfolio_builder import (
    export_portfolio_zip as _portfolio_export_zip,
    read_portfolio as _portfolio_read,
    portfolio_state as _portfolio_state,
)


def get_portfolio(h) -> None:
    h._send_json(_portfolio_read(h._config()))


def get_portfolio_preview(h) -> None:
    data = _portfolio_read(h._config())
    html = str(data.get("html") or "")
    css = str(data.get("css") or "")
    # Inline the stylesheet for the live preview so the iframe can never
    # render a stale, browser-cached style.css after a theme switch.
    # The on-disk index.html keeps the <link> for real publishing.
    if css and 'href="style.css"' in html:
        html = html.replace(
            '<link rel="stylesheet" href="style.css" />',
            f"<style>\n{css}\n</style>",
        )
    body = html.encode("utf-8")
    h.send_response(HTTPStatus.OK)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    # The preview can contain user/AI-authored HTML. The iframe is sandboxed
    # WITHOUT allow-same-origin (opaque origin), so its scripts run — the
    # portfolio's own reveal/theme script needs this to render — but cannot read
    # the parent dashboard's CSRF token or call mutating local APIs as us.
    # Inline scripts/styles are part of the generated portfolio, so allow them.
    h.send_header(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; frame-ancestors 'self'",
    )
    h.end_headers()
    h.wfile.write(body)
    return None


def get_portfolio_style_css(h) -> None:
    data = _portfolio_read(h._config())
    body = str(data.get("css") or "").encode("utf-8")
    h.send_response(HTTPStatus.OK)
    h.send_header("Content-Type", "text/css; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)
    return None


def get_portfolio_export(h) -> None:
    zip_path = _portfolio_export_zip(h._config())
    body = zip_path.read_bytes()
    h.send_response(HTTPStatus.OK)
    h.send_header("Content-Type", "application/zip")
    h.send_header("Content-Disposition", 'attachment; filename="portfolio_export.zip"')
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)
    return None


def get_portfolio_asset(h, parsed) -> None:
    """Serve a portfolio asset file by name (the ``/api/portfolio/<name>`` prefix)."""
    name = Path(parsed.path.rsplit("/", 1)[-1]).name
    root = Path(_portfolio_state(h._config())["path"]).resolve()
    asset = (root / name).resolve()
    if root in asset.parents and asset.exists() and asset.is_file():
        return h._send_file(str(asset))
    return h._send_error_json("Portfolio asset not found.", HTTPStatus.NOT_FOUND)
