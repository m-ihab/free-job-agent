"""Form-filling orchestrators for auto-apply.

Drives the per-ATS fill flows (France Travail apply button, LinkedIn Easy Apply,
standard ATS, generic HTML), plus file upload, cover-letter fill, submit, and the
human-readable summary. Field detection lives in
:mod:`job_agent.auto_apply.driver_fields`; both are re-exported by
:mod:`job_agent.auto_apply.driver`.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from job_agent.auto_apply.detect import _detect_ats
from job_agent.auto_apply.driver_fields import _fill_visible_fields

logger = logging.getLogger(__name__)


# ── France Travail apply button ───────────────────────────────────────────────


def _click_postuler(page: Any) -> str | None:
    """Click the apply button on a France Travail detail page.

    Returns the detected ATS type of the destination page, or None if the
    click succeeded but the ATS is unknown.
    """
    selectors = [
        "button:has-text('Postuler')",
        "a:has-text('Postuler')",
        "button:has-text('Je postule')",
        "a:has-text('Je postule')",
        "button:has-text('Candidater')",
        "a:has-text('Candidater')",
        "[data-testid='apply-btn']",
        "[class*='postuler']",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click()
                page.wait_for_timeout(2500)
                new_url = page.url
                return _detect_ats(new_url) or None
        except Exception:
            continue
    return None


# ── Form fillers ──────────────────────────────────────────────────────────────


def _fill_linkedin(page: Any, qa: dict, cv_path: str, cover_md: str) -> tuple[bool, str]:
    """Click Easy Apply, walk through all modal steps, fill fields."""
    filled_fields: list[str] = []
    try:
        # Click Easy Apply button if present
        easy_btn = page.locator("button:has-text('Easy Apply'), button.jobs-apply-button").first
        if easy_btn.count():
            easy_btn.click()
            page.wait_for_timeout(1500)

        # Walk up to 8 modal pages
        for _step in range(8):
            _fill_visible_fields(page, qa, filled_fields)
            # Upload resume if prompted
            if cv_path:
                _upload_file(page, cv_path, "resume")
            # Cover letter textarea
            _fill_cover_letter(page, cover_md)
            # Check for "Next" / "Review" / "Submit" button
            next_btn = page.locator("button:has-text('Next'), button:has-text('Continue'), button:has-text('Review')").first
            submit_btn = page.locator("button:has-text('Submit application'), button:has-text('Submit')").first
            if submit_btn.count() and submit_btn.is_visible():
                break  # reached final step
            if next_btn.count() and next_btn.is_visible():
                next_btn.click()
                page.wait_for_timeout(1000)
            else:
                break

        summary = _build_summary(filled_fields, qa)
        return True, summary
    except Exception as exc:
        return False, f"LinkedIn fill error: {exc}"


def _fill_standard_ats(page: Any, qa: dict, cv_path: str, cover_md: str) -> tuple[bool, str]:
    """Fill Greenhouse / Lever / Ashby / SmartRecruiters standard forms."""
    filled_fields: list[str] = []
    try:
        _fill_visible_fields(page, qa, filled_fields)
        if cv_path:
            _upload_file(page, cv_path, "resume")
        _fill_cover_letter(page, cover_md)
        summary = _build_summary(filled_fields, qa)
        return True, summary
    except Exception as exc:
        return False, f"ATS fill error: {exc}"


def _fill_generic(page: Any, qa: dict, cv_path: str, cover_md: str) -> tuple[bool, str]:
    """Best-effort filler for any HTML form."""
    filled_fields: list[str] = []
    try:
        _fill_visible_fields(page, qa, filled_fields)
        if cv_path:
            _upload_file(page, cv_path, "resume")
        _fill_cover_letter(page, cover_md)
        summary = _build_summary(filled_fields, qa)
        return True, summary
    except Exception as exc:
        return False, f"Generic fill error: {exc}"


# ── File upload / cover letter / submit ───────────────────────────────────────


def _upload_file(page: Any, file_path: str, field_hint: str = "resume") -> None:
    if not file_path or not os.path.exists(file_path):
        return
    try:
        # Look for file input with matching label
        inputs = page.locator("input[type='file']:visible").all()
        if not inputs:
            # Some ATS hide the input — try clicking the upload button
            upload_btn = page.locator(
                "button:has-text('Upload'), label:has-text('Upload'), "
                "button:has-text('Attach'), label:has-text('CV'), label:has-text('Resume')"
            ).first
            if upload_btn.count():
                upload_btn.click()
                page.wait_for_timeout(800)
                inputs = page.locator("input[type='file']").all()
        if inputs:
            inputs[0].set_input_files(file_path)
    except Exception as exc:
        logger.debug("File upload failed: %s", exc)


def _fill_cover_letter(page: Any, cover_md: str) -> None:
    if not cover_md:
        return
    try:
        cover_text = cover_md.strip()
        # Look for a cover letter textarea
        for selector in [
            "textarea[name*='cover']",
            "textarea[id*='cover']",
            "textarea[placeholder*='cover']",
            "textarea[placeholder*='lettre']",
            "textarea[aria-label*='cover']",
        ]:
            el = page.locator(selector).first
            if el.count() and el.is_visible():
                el.fill(cover_text[:3000])
                return
    except Exception as exc:
        logger.debug("Cover letter fill failed: %s", exc)


def _click_submit(page: Any, ats: str) -> bool:
    """Click the final submit button. Returns True if clicked."""
    selectors = [
        "button:has-text('Submit application')",
        "button:has-text('Submit Application')",
        "button:has-text('Apply')",
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Send application')",
        "button:has-text('Envoyer')",
        "button:has-text('Postuler')",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible() and btn.is_enabled():
                btn.click()
                return True
        except Exception:
            continue
    return False


def _build_summary(filled: list[str], qa: dict) -> str:
    if not filled:
        return "No fields were auto-filled. Please fill the form manually then click Submit."
    lines = ["Fields filled automatically:"]
    lines.extend(f"  ✓ {f}" for f in filled)
    qa_not_filled = [k for k in qa if not any(k[:20] in f for f in filled)]
    if qa_not_filled:
        lines.append("Fields from profile NOT auto-matched (check manually):")
        lines.extend(f"  ? {k}" for k in qa_not_filled[:8])
    return "\n".join(lines)


def _screenshot_b64(page: Any) -> str:
    try:
        import base64
        data = page.screenshot(type="png")
        return base64.b64encode(data).decode("ascii")
    except Exception:
        return ""
