"""ATS + human-presence wall detection for the auto-apply engine.

Detection only — wall handling never bypasses CAPTCHAs / anti-bot controls.
This module sits at the bottom of the dependency DAG (no internal imports).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── ATS detection helpers ─────────────────────────────────────────────────────

_ATS_SIGNATURES = {
    "linkedin":      ["linkedin.com/jobs", "linkedin.com/easy-apply"],
    "greenhouse":    ["boards.greenhouse.io", "greenhouse.io/embed/job_app"],
    "lever":         ["jobs.lever.co", "lever.co/apply"],
    "ashby":         ["jobs.ashbyhq.com", "app.ashbyhq.com"],
    "workday":       ["myworkdayjobs.com", "workday.com/en-US/pages/jobs"],
    "smartrecruiters": ["jobs.smartrecruiters.com"],
    "recruitee":     [".recruitee.com"],
    "personio":      [".jobs.personio"],
}


def _detect_ats(url: str) -> str:
    url_lower = (url or "").lower()
    for ats, patterns in _ATS_SIGNATURES.items():
        if any(p in url_lower for p in patterns):
            return ats
    return "generic"


# ── Human-presence wall detection (detection only — never bypassed) ───────────

_WALL_SIGNATURES = {
    "reCAPTCHA": ["g-recaptcha", "google.com/recaptcha", "grecaptcha"],
    "hCaptcha": ["hcaptcha.com", "h-captcha"],
    "Cloudflare Turnstile": ["challenges.cloudflare.com", "cf-turnstile"],
    "Cloudflare challenge": ["cf-chl", "checking your browser before accessing"],
    "login required": [
        "please log in to continue",
        "sign in to apply",
        "log in to apply",
        "you must be logged in",
    ],
}


def _detect_human_wall(page: Any) -> tuple[bool, str]:
    """Recognize a CAPTCHA / login / anti-bot wall so full-auto can hand off.

    This only *detects* the wall (reads the DOM + iframe URLs for known markers).
    It never solves or circumvents it — that would mean defeating a third party's
    access control. Returns ``(is_wall, reason)``.
    """
    try:
        html = (page.content() or "").lower()
    except Exception:  # pragma: no cover - page may be mid-navigation
        return False, ""
    frame_urls = ""
    try:
        frame_urls = " ".join((getattr(f, "url", "") or "") for f in page.frames).lower()
    except Exception:  # pragma: no cover
        frame_urls = ""
    haystack = f"{html} {frame_urls}"
    for reason, markers in _WALL_SIGNATURES.items():
        if any(marker in haystack for marker in markers):
            return True, reason
    return False, ""


# ── France Travail helpers ────────────────────────────────────────────────────


def _is_france_travail_detail(url: str) -> bool:
    lower = (url or "").lower()
    return "candidat.francetravail.fr" in lower or "francetravail.fr/offres" in lower
