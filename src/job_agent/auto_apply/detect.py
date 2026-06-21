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
        # French walls — the whole tool targets the French market, so an
        # English-only signature list would walk straight past them.
        "connectez-vous",
        "identifiez-vous",
        "veuillez vous connecter",
        "connexion requise",
        "se connecter pour postuler",
        "acces reserve",
        "accès réservé",
    ],
}


def _detect_human_wall(page: Any) -> tuple[bool, str]:
    """Recognize a CAPTCHA / login / anti-bot wall so full-auto can hand off.

    This only *detects* the wall (reads the main DOM, each iframe URL, and each
    iframe's DOM for known markers). It never solves or circumvents it — that
    would mean defeating a third party's access control. Returns
    ``(is_wall, reason)``.

    Fails CLOSED everywhere: any part of the page we cannot inspect is treated
    as a possible wall and handed off, never proceeded past with a blind submit.
    """
    try:
        html = (page.content() or "").lower()
    except Exception:  # pragma: no cover - page may be mid-navigation
        return True, "wall detection unavailable"

    parts = [html]
    try:
        frames = list(page.frames)
    except Exception:  # pragma: no cover - frames may be unavailable mid-nav
        # A wall often lives in an iframe; if we cannot even enumerate frames we
        # must assume one might be present rather than declaring the page clear.
        return True, "wall detection unavailable"

    for frame in frames:
        parts.append((getattr(frame, "url", "") or "").lower())
        # A CAPTCHA can sit entirely inside an iframe whose URL is not a known
        # signature, so inspect the frame's DOM too when it is reachable.
        frame_content = getattr(frame, "content", None)
        if callable(frame_content):
            try:
                frame_html = frame_content()
            except Exception:
                # An unreadable frame might be hiding the wall — fail closed.
                return True, "wall detection unavailable"
            if frame_html:
                parts.append(str(frame_html).lower())

    haystack = " ".join(parts)
    for reason, markers in _WALL_SIGNATURES.items():
        if any(marker in haystack for marker in markers):
            return True, reason
    return False, ""


# ── France Travail helpers ────────────────────────────────────────────────────


def _is_france_travail_detail(url: str) -> bool:
    lower = (url or "").lower()
    return "candidat.francetravail.fr" in lower or "francetravail.fr/offres" in lower
