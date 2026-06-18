"""Automated application engine — drives Chrome via Playwright (free, no API key needed).

Uses a dedicated local browser profile by default, so the session can stay
logged in without colliding with the user's normal Chrome window. Supports:

  • LinkedIn Easy Apply (full modal flow)
  • Greenhouse public ATS forms
  • Lever public ATS forms
  • Ashby public ATS forms
  • Generic HTML forms (label-match heuristic)

Two apply modes:
  FILL_AND_CONFIRM  Playwright fills every detectable field, then pauses.
                    The dashboard shows a confirmation modal; the user clicks
                    Submit or Skip.
  FULL_AUTO         Genuinely hands-off: Playwright fills and submits without any
                    per-job confirmation. The run never blocks. If it detects a
                    human-presence wall (CAPTCHA, login challenge, anti-bot
                    interstitial) it does NOT attempt to defeat it — it saves the
                    prepared packet as a draft, marks the job ``NEEDS_MANUAL``,
                    and moves on. Those jobs surface in the dashboard's
                    "Needs manual apply" queue for the user to finish by hand.

Wall handling is detection-only by design. Bypassing CAPTCHAs / anti-bot
controls is out of scope: it circumvents third-party access controls and risks
account bans. We detect and hand off instead.

Dependencies:  playwright (pip install playwright && playwright install chromium)
               No API key, no paid service.

This package preserves the public surface of the former single-module
``auto_apply.py``. It is split into a clean dependency DAG:
``detect`` <- ``driver`` <- ``session``.
"""
from __future__ import annotations

from job_agent.apply_bridge import get_ready_candidates
from job_agent.auto_apply.detect import (
    _ATS_SIGNATURES,
    _WALL_SIGNATURES,
    _detect_ats,
    _detect_human_wall,
    _is_france_travail_detail,
)
from job_agent.auto_apply.driver import (
    _AUTO_APPLY_PROFILE_ENV,
    _USE_REAL_CHROME_PROFILE_ENV,
    _HEURISTIC_KEYS,
    BrowserProfileSelection,
    _PlaywrightNotInstalled,
    _build_apply_qa,
    _build_summary,
    _check_playwright,
    _click_postuler,
    _click_submit,
    _dedicated_browser_profile,
    _field_label,
    _fill_cover_letter,
    _fill_generic,
    _fill_linkedin,
    _fill_standard_ats,
    _fill_visible_fields,
    _find_chrome_profile,
    _heuristic_match,
    _launch_browser_context,
    _profile_lock_markers,
    _profile_looks_locked,
    _screenshot_b64,
    _select_browser_profile,
    _truthy_env,
    _upload_file,
)
from job_agent.auto_apply.session import (
    ApplyEvent,
    ApplyMode,
    ApplyResult,
    AutoApplySession,
    _finish_session_state,
    cancel,
    confirm,
    get_candidates_preview,
    get_event_queue,
    get_state,
    open_browser_for_login,
    skip,
    start,
)

__all__ = [
    # Enums / DTOs
    "ApplyMode",
    "ApplyEvent",
    "ApplyResult",
    "AutoApplySession",
    # Detection
    "_detect_ats",
    "_detect_human_wall",
    "_is_france_travail_detail",
    "_ATS_SIGNATURES",
    "_WALL_SIGNATURES",
    # Driver / form filling
    "_click_postuler",
    "_fill_linkedin",
    "_fill_standard_ats",
    "_fill_generic",
    "_fill_visible_fields",
    "_field_label",
    "_HEURISTIC_KEYS",
    "_heuristic_match",
    "_build_apply_qa",
    "_build_summary",
    "_upload_file",
    "_fill_cover_letter",
    "_click_submit",
    "_screenshot_b64",
    # Browser profile / launch
    "BrowserProfileSelection",
    "_truthy_env",
    "_AUTO_APPLY_PROFILE_ENV",
    "_USE_REAL_CHROME_PROFILE_ENV",
    "_dedicated_browser_profile",
    "_profile_lock_markers",
    "_profile_looks_locked",
    "_select_browser_profile",
    "_launch_browser_context",
    "_find_chrome_profile",
    "_PlaywrightNotInstalled",
    "_check_playwright",
    # Session API
    "get_candidates_preview",
    "get_state",
    "get_event_queue",
    "_finish_session_state",
    "start",
    "confirm",
    "skip",
    "cancel",
    "open_browser_for_login",
    # Shared dependency (patched by tests)
    "get_ready_candidates",
]
