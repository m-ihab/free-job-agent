"""Reason taxonomy for fail-closed manual application handoffs."""
from __future__ import annotations

import re

_RULES = [
    ("CAPTCHA", "Human verification", r"\bcaptcha\b|recaptcha|hcaptcha"),
    ("LOGIN_WALL", "Login required", r"\blogin\b|sign[ -]?in|connexion|authent"),
    ("ANTI_BOT", "Anti-bot wall", r"anti[- ]?bot|bot detection|cloudflare|human presence"),
    ("RATE_LIMIT", "Rate limited", r"rate limit|too many requests|429"),
    ("UNKNOWN_FIELD", "Unknown required field", r"unknown .*field|required field|missing answer|screening"),
    ("UPLOAD_FAILED", "Upload failed", r"upload|cv|resume|file"),
    ("UNSUPPORTED_ATS", "Unsupported application flow", r"unsupported|unknown ats|layout"),
    ("SUBMIT_UNCLEAR", "Unclear submit state", r"unclear|submit state|confirmation"),
]


def categorize_manual_reason(reason: str) -> dict[str, str]:
    text = str(reason or "").strip()
    if not text:
        return {"category": "UNSPECIFIED", "label": "Needs review", "reason": ""}
    for category, label, pattern in _RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return {"category": category, "label": label, "reason": text}
    return {"category": "OTHER", "label": "Needs manual review", "reason": text}
