from __future__ import annotations

import re
from pathlib import Path


APP_JS = Path("src/job_agent/ui/static/app.js")


def test_dashboard_uses_safe_href_for_server_sourced_links() -> None:
    """Server/API URLs must be protocol-checked before entering href attributes."""
    source = APP_JS.read_text(encoding="utf-8")

    assert "function safeHref(" in source
    assert "protocol === \"http:\"" in source
    assert "protocol === \"https:\"" in source

    unsafe_patterns = [
        r'href="\$\{escapeHtml\(link\.url\)\}"',
        r'href="\$\{escapeHtml\(job\.apply_url\)\}"',
        r'href="\$\{escapeHtml\(repo\.url\)\}"',
        r'href="\$\{escapeHtml\(cert\.url\)\}"',
    ]
    for pattern in unsafe_patterns:
        assert not re.search(pattern, source), pattern


def test_dashboard_safe_href_rejects_javascript_protocol() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    helper = re.search(r"function safeHref\(value\) \{(?P<body>.*?)\n\}", source, re.S)
    assert helper, "safeHref helper is missing"
    body = helper.group("body").lower()

    assert "javascript:" not in body
    assert "return \"#\"" in body
