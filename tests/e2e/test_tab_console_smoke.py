"""R3 split gate: click every tab; no uncaught page errors, no error-class console output.

The dashboard is classic shared-scope JS: an extraction mistake surfaces as a
ReferenceError/TypeError at init (bindEvents) or on first tab activation —
places markup-only assertions never look. This test is the automated form of
the DEEP-HANDOFF §3 manual click-through requirement and MUST stay green after
every static/*.js extraction.
"""
from __future__ import annotations

import re

import pytest

try:
    from playwright.sync_api import Page

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    from typing import Any

    Page = Any  # type: ignore[assignment]
    PLAYWRIGHT_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="playwright is not installed")

# The failure classes a shared-scope split produces. Benign network noise
# (favicon 404s etc.) deliberately stays out of this gate.
ERROR_CLASS = re.compile(
    r"ReferenceError|SyntaxError|TypeError|is not defined|is not a function"
)


def test_every_tab_activates_without_js_errors(page: Page, live_server_url: str) -> None:
    page_errors: list[str] = []
    console_errors: list[str] = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )

    page.goto(live_server_url)

    tabs = page.locator("nav.tabs button[data-tab]")
    names = [tabs.nth(i).get_attribute("data-tab") for i in range(tabs.count())]
    assert names, "no tabs found — dashboard failed to render"

    for name in names:
        page.locator(f"button[data-tab='{name}']").click()
        page.locator(f"#tab-{name}").wait_for(state="visible")

    # Let the async tab loaders (api fetches) finish so their failures surface.
    page.wait_for_timeout(800)

    assert page_errors == [], f"uncaught page errors after tab sweep: {page_errors}"
    bad_console = [m for m in console_errors if ERROR_CLASS.search(m)]
    assert bad_console == [], f"error-class console output: {bad_console}"
