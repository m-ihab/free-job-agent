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
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from job_agent.apply_bridge import get_ready_candidates

logger = logging.getLogger(__name__)

_AUTO_APPLY_PROFILE_ENV = "JOB_AGENT_AUTO_APPLY_PROFILE_DIR"
_USE_REAL_CHROME_PROFILE_ENV = "JOB_AGENT_AUTO_APPLY_USE_REAL_CHROME_PROFILE"

# ── Enums / DTOs ─────────────────────────────────────────────────────────────


class ApplyMode(str, Enum):
    FILL_AND_CONFIRM = "fill_and_confirm"
    FULL_AUTO = "full_auto"


@dataclass
class ApplyEvent:
    kind: str  # progress | pending_confirm | needs_manual | result | done | error
    job_id: str = ""
    packet_id: str = ""
    message: str = ""
    summary: str = ""
    screenshot_b64: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class ApplyResult:
    job_id: str
    packet_id: str
    status: str  # submitted | skipped | needs_manual | error
    message: str = ""


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


# ── Core session ──────────────────────────────────────────────────────────────


class AutoApplySession:
    """One session: iterates N candidates using Playwright."""

    def __init__(
        self,
        config: Any,
        mode: ApplyMode = ApplyMode.FILL_AND_CONFIRM,
        min_score: float = 70.0,
        limit: int = 10,
        headless: bool = False,
        job_ids: "list[str] | None" = None,
    ) -> None:
        self.config = config
        self.mode = mode
        self.min_score = min_score
        self.limit = limit
        self.headless = headless
        self.job_ids = job_ids  # if set, only apply to these job IDs

        self._progress_queue: queue.Queue[ApplyEvent] = queue.Queue()
        self._confirm_event = threading.Event()
        self._skip_flag = False
        self._cancel_flag = False
        self._running = False

    # ── Control interface ─────────────────────────────────────────────────────

    @property
    def progress_queue(self) -> "queue.Queue[ApplyEvent]":
        return self._progress_queue

    @property
    def running(self) -> bool:
        return self._running

    def confirm_submit(self) -> None:
        self._skip_flag = False
        self._confirm_event.set()

    def skip_current(self) -> None:
        self._skip_flag = True
        self._confirm_event.set()

    def cancel(self) -> None:
        self._cancel_flag = True
        self._confirm_event.set()

    def _reset_per_job_flags(self) -> None:
        """Reset per-job state so a skip/cancel on one job doesn't bleed into the next."""
        self._skip_flag = False

    def run_in_background(self) -> threading.Thread:
        t = threading.Thread(target=self._run, daemon=True, name="auto-apply")
        t.start()
        return t

    # ── Session loop ──────────────────────────────────────────────────────────

    def _emit(self, event: ApplyEvent) -> None:
        self._progress_queue.put(event)
        logger.info("[auto-apply] %s — %s", event.kind, event.message[:140])

    def _run(self) -> None:
        self._running = True
        results: list[ApplyResult] = []
        error_message: str | None = None
        try:
            _check_playwright()
            candidates = self._load_candidates()
            if not candidates:
                self._emit(ApplyEvent("done", message="No ready packets found. Run the autopilot or generate packets first."))
                return

            self._emit(ApplyEvent("progress", message=f"Found {len(candidates)} ready packet(s). Opening browser…"))

            # Location pre-flight — let the user see what they're about to apply to.
            _loc_lines = "; ".join(
                f"{c.job.title} @ {c.job.company} ({c.job.location or 'location unknown'})"
                for c in candidates[:6]
            )
            self._emit(ApplyEvent(
                "preflight",
                message=f"Applying to: {_loc_lines}",
                data={"count": len(candidates), "locations": [c.job.location for c in candidates]},
            ))

            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                profile = _select_browser_profile(self.config)
                if profile.warning:
                    self._emit(ApplyEvent("progress", message=profile.warning))
                self._emit(ApplyEvent(
                    "progress",
                    message=(
                        f"Using {profile.label} browser profile: {profile.path}. "
                        "If a login page appears, sign in once; Job Agent will reuse it next time."
                    ),
                ))
                ctx = _launch_browser_context(p, profile.path, self.headless)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()

                for i, candidate in enumerate(candidates, 1):
                    if self._cancel_flag:
                        break
                    self._reset_per_job_flags()
                    self._emit(ApplyEvent(
                        "progress",
                        job_id=candidate.job.id,
                        packet_id=candidate.packet.id,
                        message=f"[{i}/{len(candidates)}] {candidate.job.title} @ {candidate.job.company}",
                    ))
                    result = self._apply_one(page, candidate, i, len(candidates))
                    results.append(result)
                    self._emit(ApplyEvent(
                        "result",
                        job_id=result.job_id,
                        packet_id=result.packet_id,
                        message=result.message,
                        data={"status": result.status},
                    ))

                try:
                    ctx.close()
                except Exception:
                    pass

            submitted = sum(1 for r in results if r.status == "submitted")
            skipped = sum(1 for r in results if r.status == "skipped")
            needs_manual = sum(1 for r in results if r.status == "needs_manual")
            errors = sum(1 for r in results if r.status == "error")
            self._emit(ApplyEvent(
                "done",
                message=(
                    f"Session complete — submitted: {submitted} · skipped: {skipped} · "
                    f"needs manual: {needs_manual} · errors: {errors}"
                ),
                data={
                    "submitted": submitted,
                    "skipped": skipped,
                    "needs_manual": needs_manual,
                    "errors": errors,
                },
            ))
        except _PlaywrightNotInstalled as exc:
            error_message = str(exc)
            self._emit(ApplyEvent("error", message=str(exc)))
        except Exception as exc:
            logger.exception("Auto-apply session crashed")
            error_message = f"Session failed: {exc}"
            self._emit(ApplyEvent("error", message=error_message))
        finally:
            self._running = False
            _finish_session_state(results, error_message)

    def _apply_one(self, page: Any, candidate: Any, index: int, total: int) -> ApplyResult:
        job = candidate.job
        packet = candidate.packet
        label = f"{job.title} @ {job.company}"
        apply_url = job.apply_url or ""
        ats = _detect_ats(apply_url)

        try:
            self._emit(ApplyEvent(
                "progress", job_id=job.id, packet_id=packet.id,
                message=f"[{index}/{total}] {label} — navigating to {ats} form…",
            ))

            page.goto(apply_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2000)

            # France Travail detail pages show a "Postuler" button — click it
            # to reach the actual application form (external ATS or FT form).
            if _is_france_travail_detail(apply_url):
                ats = _click_postuler(page) or ats

            filled, summary = self._fill_form(page, candidate, ats)

            if not filled:
                if self.mode == ApplyMode.FULL_AUTO:
                    wall, reason = _detect_human_wall(page)
                    if wall:
                        return self._queue_needs_manual(candidate, summary, reason)
                return ApplyResult(job.id, packet.id, "error",
                                   f"Could not fill form for {label}: {summary}")

            # Gate before submit
            if self.mode == ApplyMode.FILL_AND_CONFIRM:
                screenshot = _screenshot_b64(page)
                self._emit(ApplyEvent(
                    "pending_confirm",
                    job_id=job.id,
                    packet_id=packet.id,
                    message=f"Form filled for {label}. Review and click Submit or Skip.",
                    summary=summary,
                    screenshot_b64=screenshot,
                ))
                self._confirm_event.clear()
                self._confirm_event.wait(timeout=300)
                if self._cancel_flag:
                    return ApplyResult(job.id, packet.id, "skipped", "Session cancelled.")
                if self._skip_flag:
                    return ApplyResult(job.id, packet.id, "skipped", f"Skipped {label}.")
            else:
                # FULL_AUTO — genuinely hands-off; the run never blocks. Detect
                # (never defeat) a human-presence wall and hand off to the manual
                # queue, otherwise submit straight away with no confirmation gate.
                if self._cancel_flag:
                    return ApplyResult(job.id, packet.id, "skipped", "Session cancelled.")
                wall, reason = _detect_human_wall(page)
                if wall:
                    return self._queue_needs_manual(candidate, summary, reason)

            # Submit
            self._emit(ApplyEvent("progress", job_id=job.id, packet_id=packet.id,
                                  message=f"[{index}/{total}] {label} — submitting…"))
            submitted = _click_submit(page, ats)
            if submitted:
                page.wait_for_timeout(3000)
                self._mark_submitted(candidate)
                return ApplyResult(job.id, packet.id, "submitted", f"Applied to {label}.")
            else:
                return ApplyResult(job.id, packet.id, "error",
                                   f"Submit button not found for {label}. Mark manually.")

        except Exception as exc:
            logger.warning("apply_one failed for %s: %s", label, exc, exc_info=True)
            return ApplyResult(job.id, packet.id, "error", f"Error on {label}: {exc}")

    # ── Form filling ──────────────────────────────────────────────────────────

    def _fill_form(self, page: Any, candidate: Any, ats: str) -> tuple[bool, str]:
        """Fill the application form. Returns (success, summary)."""
        profile = self._profile()
        qa = _build_apply_qa(profile, candidate.packet.qa_answers or {})
        cv_path = candidate.packet.tailored_cv_pdf_path or ""
        cover_md = candidate.packet.cover_letter_md or ""

        if ats == "linkedin":
            return _fill_linkedin(page, qa, cv_path, cover_md)
        if ats in ("greenhouse", "lever", "ashby", "recruitee", "smartrecruiters"):
            return _fill_standard_ats(page, qa, cv_path, cover_md)
        return _fill_generic(page, qa, cv_path, cover_md)

    def _profile(self) -> Any:
        """Load candidate profile (cached on the session object)."""
        if not hasattr(self, "_profile_cache"):
            try:
                from job_agent.validators import load_profile_bundle
                profile, _, _ = load_profile_bundle(self.config)
                self._profile_cache = profile
            except Exception:
                self._profile_cache = None
        return self._profile_cache

    def _load_candidates(self) -> list:
        candidates = get_ready_candidates(min_score=self.min_score, limit=self.limit)
        if self.job_ids is not None:
            allowed = set(self.job_ids)
            candidates = [c for c in candidates if c.job.id in allowed]
        return candidates

    def _mark_submitted(self, candidate: Any) -> None:
        from job_agent.db.database import Database
        from job_agent.schemas.job import JobStatus
        from job_agent.schemas.packet import PacketStatus

        db = Database(self.config.db_path)
        db.initialize()
        db.update_job_status(candidate.job.id, JobStatus.MANUALLY_SUBMITTED)
        for pkt in db.get_packets_for_job(candidate.job.id):
            if pkt.id == candidate.packet.id:
                pkt.status = PacketStatus.MANUALLY_SUBMITTED
                db.save_packet(pkt)
                break
        db.log_event(
            candidate.job.id,
            "MANUALLY_SUBMITTED",
            {"packet_id": candidate.packet.id, "note": "Auto-apply session"},
            packet_id=candidate.packet.id,
        )
        try:
            from job_agent.exporters.internship_workbook import export_applied_internships
            export_applied_internships(self.config)
        except Exception as exc:
            logger.warning("Excel export after submit: %s", exc)

    def _mark_needs_manual(self, candidate: Any, reason: str) -> None:
        """Flag a job for manual apply (full-auto hit a wall). The prepared
        packet is left intact as the ready-to-submit draft."""
        from job_agent.db.database import Database
        from job_agent.schemas.job import JobStatus

        db = Database(self.config.db_path)
        db.initialize()
        db.update_job_status(candidate.job.id, JobStatus.NEEDS_MANUAL)
        db.log_event(
            candidate.job.id,
            "NEEDS_MANUAL",
            {"packet_id": candidate.packet.id, "reason": reason, "note": "Full-auto hand-off"},
            packet_id=candidate.packet.id,
        )

    def _queue_needs_manual(self, candidate: Any, summary: str, reason: str) -> ApplyResult:
        """Persist the hand-off, emit an event, and return a needs_manual result.
        The session loop keeps going — full-auto never blocks on a wall."""
        job = candidate.job
        packet = candidate.packet
        label = f"{job.title} @ {job.company}"
        try:
            self._mark_needs_manual(candidate, reason)
        except Exception as exc:  # persistence must not abort the run
            logger.warning("Could not mark %s needs_manual: %s", label, exc)
        self._emit(ApplyEvent(
            "needs_manual",
            job_id=job.id,
            packet_id=packet.id,
            message=f"{label} needs manual apply ({reason}). Draft saved; continuing.",
            summary=summary,
            data={"reason": reason},
        ))
        return ApplyResult(
            job.id, packet.id, "needs_manual",
            f"{label}: {reason} — draft queued for manual apply.",
        )


# ── France Travail helpers ────────────────────────────────────────────────────


def _is_france_travail_detail(url: str) -> bool:
    lower = (url or "").lower()
    return "candidat.francetravail.fr" in lower or "francetravail.fr/offres" in lower


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
    for field in fields:
        try:
            field_type = field.get_attribute("type") or "text"
            if field_type in ("file", "hidden", "submit", "button", "reset", "image"):
                continue

            label_text = _field_label(page, field)
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

            tag = field.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                # Try to select matching option
                try:
                    field.select_option(label=answer, timeout=1000)
                    filled.append(f"{label_text}: {answer[:60]}")
                except Exception:
                    pass
            elif field_type == "checkbox":
                if str(answer).lower() in ("yes", "true", "1", "oui"):
                    if not field.is_checked():
                        field.check()
                    filled.append(f"{label_text}: checked")
            else:
                field.fill(str(answer))
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


def get_candidates_preview(min_score: float = 65.0, limit: int = 10) -> list[dict]:
    """Return a preview list of candidates that would be processed by auto-apply.

    Returns plain dicts safe for JSON serialisation.  No browser is opened.
    """
    candidates = get_ready_candidates(min_score=min_score, limit=limit)
    return [
        {
            "job_id": c.job.id,
            "title": c.job.title,
            "company": c.job.company,
            "location": c.job.location or "",
            "apply_url": c.job.apply_url or "",
            "packet_id": c.packet.id,
            "fit_score": c.packet.fit_score,
        }
        for c in candidates
    ]


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
        real_profile = _find_chrome_profile()
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


# ── Module-level singleton state (shared with server.py) ─────────────────────


_session_lock = threading.Lock()
_state: dict = {
    "running": False,
    "mode": "fill_and_confirm",
    "started_at": None,
    "results_count": {"submitted": 0, "skipped": 0, "errors": 0},
    "error": None,
}
_event_queue: queue.Queue[ApplyEvent] = queue.Queue()
_active: AutoApplySession | None = None


def get_state() -> dict:
    return dict(_state)


def get_event_queue() -> "queue.Queue[ApplyEvent]":
    return _event_queue


def _finish_session_state(results: list[ApplyResult], error_message: str | None = None) -> None:
    global _state
    submitted = sum(1 for r in results if r.status == "submitted")
    skipped = sum(1 for r in results if r.status == "skipped")
    errors = sum(1 for r in results if r.status == "error")
    if error_message:
        errors = max(errors, 1)
    with _session_lock:
        _state = {
            **_state,
            "running": False,
            "results_count": {"submitted": submitted, "skipped": skipped, "errors": errors},
            "error": error_message,
        }


def start(
    config: Any,
    mode: str,
    min_score: float,
    limit: int,
    job_ids: "list[str] | None" = None,
) -> dict:
    global _active, _state
    with _session_lock:
        if _state["running"]:
            return {"ok": False, "error": "A session is already running."}
        import datetime
        _state = {
            "running": True,
            "mode": mode,
            "started_at": datetime.datetime.now().isoformat(),
            "results_count": {"submitted": 0, "skipped": 0, "errors": 0},
            "error": None,
        }
        while not _event_queue.empty():
            try:
                _event_queue.get_nowait()
            except queue.Empty:
                break

        _active = AutoApplySession(
            config=config,
            mode=ApplyMode(mode),
            min_score=min_score,
            limit=limit,
            job_ids=job_ids if job_ids else None,
        )
        _active._progress_queue = _event_queue
        _active.run_in_background()
    return {"ok": True, "state": get_state()}


def open_browser_for_login(config: Any) -> dict:
    """Open the dedicated Job Agent browser profile so the user can log in.

    Launches the browser window in the foreground.  The user logs in to
    France Travail, LinkedIn, etc.  Closing the browser persists cookies in
    the dedicated profile directory for future sessions.
    """
    try:
        _check_playwright()
    except _PlaywrightNotInstalled as exc:
        return {"ok": False, "error": str(exc)}

    profile = _select_browser_profile(config)
    try:
        from playwright.sync_api import sync_playwright

        def _open() -> None:
            with sync_playwright() as p:
                ctx = _launch_browser_context(p, profile.path, headless=False)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto("https://candidat.francetravail.fr/espacepersonnel/", wait_until="domcontentloaded", timeout=15_000)
                logger.info("[auto-apply] login-setup browser opened at %s", profile.path)
                # Keep browser open until the user closes it
                try:
                    ctx.wait_for_event("close", timeout=0)
                except Exception:
                    pass

        t = threading.Thread(target=_open, daemon=True, name="login-setup")
        t.start()
        return {
            "ok": True,
            "profile_path": str(profile.path),
            "message": (
                "Browser opened with the Job Agent profile. "
                "Log in to France Travail and any other sites, then close the browser. "
                "Job Agent will reuse your session next time."
            ),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def confirm() -> dict:
    with _session_lock:
        if _active:
            _active.confirm_submit()
            return {"ok": True}
    return {"ok": False, "error": "No active session."}


def skip() -> dict:
    with _session_lock:
        if _active:
            _active.skip_current()
            return {"ok": True}
    return {"ok": False, "error": "No active session."}


def cancel() -> dict:
    with _session_lock:
        if _active:
            _active.cancel()
            return {"ok": True}
    return {"ok": False, "error": "No active session."}
