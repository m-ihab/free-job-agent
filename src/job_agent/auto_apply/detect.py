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
    "workable":      ["apply.workable.com", ".workable.com/j/", "workable.com/j/"],
}


def _detect_ats(url: str) -> str:
    url_lower = (url or "").lower()
    for ats, patterns in _ATS_SIGNATURES.items():
        if any(p in url_lower for p in patterns):
            return ats
    return "generic"


# ── Structured hand-off reason codes ──────────────────────────────────────────

# Stable machine-readable codes for the human-readable wall reasons, so the
# dashboard "Needs manual apply" queue and the events log can group hand-offs.
_REASON_CODES = {
    "reCAPTCHA": "captcha",
    "hCaptcha": "captcha",
    "Cloudflare Turnstile": "anti_bot",
    "Cloudflare challenge": "anti_bot",
    "login required": "login_wall",
    "wall detection unavailable": "detection_failed",
}


def reason_code(reason: str) -> str:
    return _REASON_CODES.get(reason, "other")


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


# ── Required-field completeness (fail-closed, FULL_AUTO only) ─────────────────

_REQUIRED_SELECTOR = (
    "input[required], select[required], textarea[required], [aria-required='true']"
)


def _field_label(element: Any) -> str:
    for attr in ("name", "id", "aria-label", "placeholder"):
        try:
            value = element.get_attribute(attr)
        except Exception:
            continue
        if value:
            return str(value)
    return "unnamed field"


def _find_unfilled_required(page: Any) -> list[str]:
    """Labels of visible required form fields that are still empty.

    Fail-closed contract: if the fields cannot be inspected at all, returns a
    sentinel entry so FULL_AUTO hands off instead of submitting a form it does
    not fully understand. An empty list means every detected required field
    holds a value.
    """
    try:
        elements = list(page.query_selector_all(_REQUIRED_SELECTOR))
    except Exception:
        logger.debug("[auto-apply] required-field enumeration failed", exc_info=True)
        return ["required-field check unavailable"]
    missing: list[str] = []
    for element in elements:
        try:
            try:
                if not element.is_visible():
                    # Hidden inputs frequently back custom widgets and receive
                    # their value programmatically; only judge what a human
                    # would be asked to fill.
                    continue
            except Exception:
                pass  # visibility unknown → keep inspecting the field
            field_type = ""
            try:
                field_type = (element.get_attribute("type") or "").lower()
            except Exception:
                pass
            if field_type in ("checkbox", "radio"):
                filled = bool(element.is_checked())
            else:
                filled = bool((element.input_value() or "").strip())
            if not filled:
                missing.append(_field_label(element))
        except Exception:
            # A field we cannot read might be a required blank — fail closed.
            logger.debug("[auto-apply] required-field inspection failed", exc_info=True)
            missing.append("uninspectable required field")
    return missing


# ── France Travail helpers ────────────────────────────────────────────────────


def _is_france_travail_detail(url: str) -> bool:
    lower = (url or "").lower()
    return "candidat.francetravail.fr" in lower or "francetravail.fr/offres" in lower
