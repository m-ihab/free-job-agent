"""Playwright form-filling, browser profile selection, and launch helpers.

This module drives Chrome via Playwright. The implementation is split for focus:
  * :mod:`job_agent.auto_apply.driver_fields` — field detection + QA matching
  * :mod:`job_agent.auto_apply.driver_fill` — per-ATS fill orchestration, submit
  * :mod:`job_agent.auto_apply.driver_browser` — profile selection + launch

This module re-exports the full surface so existing imports
(``from job_agent.auto_apply.driver import ...``) keep working unchanged.
"""
from __future__ import annotations

from job_agent.auto_apply.driver_browser import (  # noqa: F401  (re-export seam)
    _AUTO_APPLY_PROFILE_ENV,
    _USE_REAL_CHROME_PROFILE_ENV,
    BrowserProfileSelection,
    _check_playwright,
    _dedicated_browser_profile,
    _find_chrome_profile,
    _launch_browser_context,
    _PlaywrightNotInstalled,
    _profile_lock_markers,
    _profile_looks_locked,
    _select_browser_profile,
    _truthy_env,
)
from job_agent.auto_apply.driver_fields import (  # noqa: F401  (re-export seam)
    _HEURISTIC_KEYS,
    _build_apply_qa,
    _field_label,
    _fill_visible_fields,
    _heuristic_match,
)
from job_agent.auto_apply.driver_fill import (  # noqa: F401  (re-export seam)
    _build_summary,
    _click_postuler,
    _click_submit,
    _fill_cover_letter,
    _fill_generic,
    _fill_linkedin,
    _fill_standard_ats,
    _screenshot_b64,
    _upload_file,
)

__all__ = [
    "_AUTO_APPLY_PROFILE_ENV",
    "_USE_REAL_CHROME_PROFILE_ENV",
    "BrowserProfileSelection",
    "_check_playwright",
    "_dedicated_browser_profile",
    "_find_chrome_profile",
    "_launch_browser_context",
    "_PlaywrightNotInstalled",
    "_profile_lock_markers",
    "_profile_looks_locked",
    "_select_browser_profile",
    "_truthy_env",
    "_HEURISTIC_KEYS",
    "_build_apply_qa",
    "_field_label",
    "_fill_visible_fields",
    "_heuristic_match",
    "_build_summary",
    "_click_postuler",
    "_click_submit",
    "_fill_cover_letter",
    "_fill_generic",
    "_fill_linkedin",
    "_fill_standard_ats",
    "_screenshot_b64",
    "_upload_file",
]
