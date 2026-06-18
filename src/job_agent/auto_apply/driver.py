"""Playwright form-filling, browser profile selection, and launch helpers.

This module drives Chrome via Playwright: it fills LinkedIn Easy Apply,
standard ATS, and generic HTML forms, uploads files, fills cover letters,
clicks submit, and manages the dedicated/real browser profile selection and
persistent-context launch. It may import from :mod:`detect`.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from job_agent.auto_apply.detect import _detect_ats

logger = logging.getLogger(__name__)

_AUTO_APPLY_PROFILE_ENV = "JOB_AGENT_AUTO_APPLY_PROFILE_DIR"
_USE_REAL_CHROME_PROFILE_ENV = "JOB_AGENT_AUTO_APPLY_USE_REAL_CHROME_PROFILE"


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


# ── Low-level field helpers ───────────────────────────────────────────────────


def _fill_visible_fields(page: Any, qa: dict, filled: list[str]) -> None:
    """Match visible form fields to QA answers by label proximity."""
    from rapidfuzz import process as fuzz_process

    qa_keys = list(qa.keys())
    if not qa_keys:
        return

    # Collect all input/textarea/select elements that are visible
    fields = page.locator("input:visible, textarea:visible, select:visible").all()
    for field_el in fields:
        try:
            field_type = field_el.get_attribute("type") or "text"
            if field_type in ("file", "hidden", "submit", "button", "reset", "image"):
                continue

            label_text = _field_label(page, field_el)
            if not label_text:
                continue

            # Fuzzy match the label against QA keys
            match = fuzz_process.extractOne(label_text, qa_keys, score_cutoff=55)
            if not match:
                # Also try matching directly against QA values by common field names
                match = _heuristic_match(label_text, qa)
                if not match:
                    continue
                key, answer = match
            else:
                key = match[0]
                answer = qa[key]

            if not answer:
                continue

            tag = field_el.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                # Try to select matching option
                try:
                    field_el.select_option(label=answer, timeout=1000)
                    filled.append(f"{label_text}: {answer[:60]}")
                except Exception:
                    pass
            elif field_type == "checkbox":
                if str(answer).lower() in ("yes", "true", "1", "oui"):
                    if not field_el.is_checked():
                        field_el.check()
                    filled.append(f"{label_text}: checked")
            else:
                field_el.fill(str(answer))
                filled.append(f"{label_text}: {str(answer)[:60]}")
        except Exception:
            continue


def _field_label(page: Any, field: Any) -> str:
    """Return the human-readable label for a form field.

    Tries multiple strategies in priority order so React/Angular ATS forms
    (which rarely use static <label for="..."> elements) are also handled.
    """
    try:
        # 1. aria-label attribute
        label = field.get_attribute("aria-label") or ""
        if label.strip():
            return label.strip()

        # 2. <label for="id">
        field_id = field.get_attribute("id") or ""
        if field_id:
            label_el = page.locator(f"label[for='{field_id}']").first
            if label_el.count():
                text = label_el.inner_text()
                if text.strip():
                    return text.strip()

        # 3. aria-labelledby — one or more referenced element IDs
        labelledby = field.get_attribute("aria-labelledby") or ""
        if labelledby:
            for ref_id in labelledby.split():
                ref_id = ref_id.strip()
                if not ref_id:
                    continue
                try:
                    ref_el = page.locator(f"#{ref_id}").first
                    if ref_el.count():
                        text = ref_el.inner_text()
                        if text.strip():
                            return text.strip()
                except Exception:
                    pass

        # 4. DOM walk — find the nearest <label> or labelling text node
        try:
            text = field.evaluate("""el => {
                let node = el.parentElement;
                for (let i = 0; i < 5; i++) {
                    if (!node) break;
                    const lbl = node.querySelector(
                        'label, [class*="label" i], [class*="Label"], legend'
                    );
                    if (lbl) {
                        const t = (lbl.innerText || lbl.textContent || '').trim();
                        if (t && t.length < 120) return t;
                    }
                    node = node.parentElement;
                }
                return '';
            }""")
            if text and text.strip():
                return text.strip()
        except Exception:
            pass

        # 5. placeholder
        ph = field.get_attribute("placeholder") or ""
        if ph.strip():
            return ph.strip()

        # 6. autocomplete attribute (e.g. "given-name", "email", "tel")
        ac = field.get_attribute("autocomplete") or ""
        if ac.strip() and ac.lower() not in ("on", "off"):
            return ac.replace("-", " ").replace("_", " ").strip()

        # 7. name attribute as last resort
        name = field.get_attribute("name") or ""
        return name.replace("_", " ").replace("-", " ").strip()
    except Exception:
        return ""


_HEURISTIC_KEYS = {
    "first name": ["first_name", "given_name", "prenom", "prénom", "firstname"],
    "last name": ["last_name", "family_name", "nom", "surname", "lastname"],
    "email": ["email", "e-mail", "courriel", "adresse email"],
    "phone": ["phone", "telephone", "téléphone", "mobile", "portable"],
    "linkedin": ["linkedin_url", "linkedin", "profil linkedin"],
    "github": ["github_url", "github"],
    "city": ["city", "ville", "location"],
    "cover letter": ["cover_letter", "lettre de motivation", "motivation"],
    "why": ["cover_letter", "motivation_text"],
    "salary": ["salary_expectation", "salaire", "pretentions salariales"],
    "work authorization": ["work_authorization", "autorisation travail", "eligible to work"],
    "start date": ["start_date", "availability", "disponibilité", "date de début"],
}


def _build_apply_qa(profile: Any, job_qa: dict) -> dict:
    """Merge candidate contact fields with job-specific QA answers.

    Contact fields (name, email, phone, …) are injected first so the form
    filler can fill even basic fields like "First name" or "Email".
    Job-specific answers take precedence when a key conflicts.
    """
    base: dict[str, str] = {}
    if profile is not None:
        contact = getattr(profile, "contact", None)
        if contact is not None:
            full_name = str(getattr(contact, "name", "") or "").strip()
            parts = full_name.split(None, 1)
            base["first_name"] = parts[0] if parts else ""
            base["last_name"] = parts[1] if len(parts) > 1 else ""
            base["full_name"] = full_name
            base["name"] = full_name
            if getattr(contact, "email", None):
                base["email"] = contact.email
            if getattr(contact, "phone", None):
                base["phone"] = contact.phone
            if getattr(contact, "linkedin_url", None):
                base["linkedin_url"] = contact.linkedin_url
            if getattr(contact, "github_url", None):
                base["github_url"] = contact.github_url
            if getattr(contact, "work_authorization", None):
                base["work_authorization"] = contact.work_authorization
            if getattr(contact, "location", None):
                base["city"] = contact.location
    # Job-specific answers override base contact fields
    return {**base, **{k: v for k, v in (job_qa or {}).items() if v}}


def _heuristic_match(label: str, qa: dict) -> tuple[str, str] | None:
    label_l = label.lower()
    for keyword, candidate_keys in _HEURISTIC_KEYS.items():
        if keyword in label_l:
            for ck in candidate_keys:
                for qa_key, qa_val in qa.items():
                    if ck in qa_key.lower() and qa_val:
                        return qa_key, qa_val
    return None


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


# ── Browser profile selection ─────────────────────────────────────────────────


@dataclass
class BrowserProfileSelection:
    path: Path
    label: str
    warning: str = ""


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _dedicated_browser_profile(config: Any) -> Path:
    """Return Job Agent's private browser profile directory."""
    custom = os.environ.get(_AUTO_APPLY_PROFILE_ENV)
    if custom:
        path = Path(custom).expanduser()
    else:
        data_dir = Path(getattr(config, "data_dir", Path.cwd() / ".job_agent"))
        path = data_dir / "browser_profiles" / "auto_apply"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _profile_lock_markers(path: Path) -> list[Path]:
    return [path / name for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")]


def _profile_looks_locked(path: Path) -> bool:
    return any(marker.exists() for marker in _profile_lock_markers(path))


def _select_browser_profile(config: Any) -> BrowserProfileSelection:
    """Pick the browser profile safely.

    The normal Chrome "User Data" directory cannot be controlled while Chrome is
    open. Using a private profile keeps sessions persistent without asking the
    user to close their daily browser.
    """
    custom = os.environ.get(_AUTO_APPLY_PROFILE_ENV)
    if custom:
        return BrowserProfileSelection(_dedicated_browser_profile(config), "custom Job Agent")

    if _truthy_env(_USE_REAL_CHROME_PROFILE_ENV):
        import job_agent.auto_apply as _pkg
        real_profile = _pkg._find_chrome_profile()
        if real_profile:
            real_path = Path(real_profile)
            if not _profile_looks_locked(real_path):
                return BrowserProfileSelection(real_path, "real Chrome")
            return BrowserProfileSelection(
                _dedicated_browser_profile(config),
                "dedicated Job Agent",
                (
                    "Your real Chrome profile is already in use, so auto-apply "
                    "switched to the dedicated Job Agent profile instead."
                ),
            )

    return BrowserProfileSelection(_dedicated_browser_profile(config), "dedicated Job Agent")


def _launch_browser_context(playwright: Any, profile_dir: Path, headless: bool) -> Any:
    """Launch a persistent browser profile with Chrome first, Chromium fallback."""
    kwargs = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "args": ["--start-maximized"] if not headless else [],
        "no_viewport": not headless,
    }
    last_exc: Exception | None = None
    channels: list[str | None] = ["chrome", None] if not headless else [None]
    for channel in channels:
        try:
            if channel:
                return playwright.chromium.launch_persistent_context(channel=channel, **kwargs)
            return playwright.chromium.launch_persistent_context(**kwargs)
        except Exception as exc:
            last_exc = exc
            msg = str(exc)
            if "Opening in existing browser session" in msg or "profile is already in use" in msg:
                raise RuntimeError(
                    "The selected browser profile is already in use. Use the default "
                    "dedicated Job Agent profile, or close every Chrome window before "
                    f"setting {_USE_REAL_CHROME_PROFILE_ENV}=1."
                ) from exc
            if channel:
                logger.info("Chrome channel launch failed; trying Playwright Chromium: %s", exc)
                continue
            break
    raise RuntimeError(
        "Could not start the Playwright browser. Run `python -m playwright install chromium` "
        f"or install Google Chrome. Last error: {last_exc}"
    )


def _find_chrome_profile() -> str | None:
    """Return the path to the user's Chrome profile directory."""
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data"),
        os.path.join(os.environ.get("APPDATA", ""), "Google", "Chrome", "User Data"),
        os.path.expanduser("~/.config/google-chrome"),
        os.path.expanduser("~/Library/Application Support/Google/Chrome"),
    ]
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return None


# ── Playwright install check ──────────────────────────────────────────────────


class _PlaywrightNotInstalled(RuntimeError):
    pass


def _check_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        raise _PlaywrightNotInstalled(
            "playwright is not installed. Run:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        )
