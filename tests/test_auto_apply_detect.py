"""ATS + human-presence wall detection (detection only — never bypassed)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from job_agent.auto_apply.detect import (
    _detect_ats,
    _detect_human_wall,
    _is_france_travail_detail,
)


class _FakePage:
    """Minimal Playwright page stub exposing .content() and .frames."""

    def __init__(self, html: str = "", frame_urls: list[str] | None = None, raise_content: bool = False):
        self._html = html
        self._raise = raise_content
        self.frames = [SimpleNamespace(url=u) for u in (frame_urls or [])]

    def content(self) -> str:
        if self._raise:
            raise RuntimeError("page mid-navigation")
        return self._html


# ── _detect_ats ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("url, expected", [
    ("https://www.linkedin.com/jobs/view/123", "linkedin"),
    ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse"),
    ("https://jobs.lever.co/acme/abc", "lever"),
    ("https://jobs.ashbyhq.com/acme/role", "ashby"),
    ("https://acme.myworkdayjobs.com/careers", "workday"),
    ("https://jobs.smartrecruiters.com/Acme/1", "smartrecruiters"),
    ("https://acme.recruitee.com/o/role", "recruitee"),
    ("https://acme.jobs.personio.de/job/1", "personio"),
])
def test_detect_ats_recognises_known_boards(url, expected):
    assert _detect_ats(url) == expected


def test_detect_ats_is_case_insensitive():
    assert _detect_ats("HTTPS://BOARDS.GREENHOUSE.IO/Acme") == "greenhouse"


@pytest.mark.parametrize("url", ["", None, "https://careers.acme.com/apply"])
def test_detect_ats_returns_generic_for_unknown(url):
    assert _detect_ats(url) == "generic"


# ── _detect_human_wall ────────────────────────────────────────────────────────


@pytest.mark.parametrize("html, frames, expected", [
    ("<div class='g-recaptcha'></div>", [], "reCAPTCHA"),
    ("<html>fine</html>", ["https://www.google.com/recaptcha/api2"], "reCAPTCHA"),
    ("<div class='h-captcha'></div>", [], "hCaptcha"),
    ("<html>ok</html>", ["https://hcaptcha.com/challenge"], "hCaptcha"),
    ("<div class='cf-turnstile'></div>", [], "Cloudflare Turnstile"),
    ("<html>Checking your browser before accessing</html>", [], "Cloudflare challenge"),
    ("<p>Please log in to continue</p>", [], "login required"),
    ("<p>Sign in to apply</p>", [], "login required"),
])
def test_detect_human_wall_positive(html, frames, expected):
    is_wall, reason = _detect_human_wall(_FakePage(html, frames))
    assert is_wall is True
    assert reason == expected


def test_detect_human_wall_clean_form_returns_false():
    page = _FakePage("<form><input name='email'><input name='name'></form>")
    assert _detect_human_wall(page) == (False, "")


def test_detect_human_wall_handles_content_exception():
    # A page we cannot inspect must fail CLOSED — treat as a wall and hand off,
    # never proceed to a blind submit.
    is_wall, reason = _detect_human_wall(_FakePage(raise_content=True))
    assert is_wall is True
    assert reason == "wall detection unavailable"


def test_detect_human_wall_unreadable_frames_fails_closed():
    # A wall often lives in an iframe. If the main DOM looks clean but we cannot
    # even enumerate frames, we must hand off, not declare the page clear.
    class NoFrames:
        def content(self):
            return "<html>clean</html>"

        @property
        def frames(self):
            raise RuntimeError("frames unavailable")

    assert _detect_human_wall(NoFrames()) == (True, "wall detection unavailable")


def test_detect_human_wall_unreadable_frame_dom_fails_closed():
    # The main DOM is clean and the iframe URL is unremarkable, but the iframe's
    # own DOM cannot be read — treat it as a possible wall.
    class _BadFrame:
        url = "https://challenge.example/widget"

        def content(self):
            raise RuntimeError("cross-origin frame")

    class _Page:
        frames = [_BadFrame()]

        def content(self):
            return "<html>clean body</html>"

    assert _detect_human_wall(_Page()) == (True, "wall detection unavailable")


def test_detect_human_wall_matches_marker_in_iframe_dom_only():
    # Clean main DOM, unremarkable iframe URL, but the CAPTCHA markup lives
    # inside the iframe's DOM — still detected.
    class _Frame:
        url = "https://widget.example/embed"

        def content(self):
            return "<div class='g-recaptcha'></div>"

    class _Page:
        frames = [_Frame()]

        def content(self):
            return "<html>clean body</html>"

    is_wall, reason = _detect_human_wall(_Page())
    assert is_wall is True
    assert reason == "reCAPTCHA"


def test_detect_human_wall_matches_french_login_wall():
    page = _FakePage("<p>Veuillez vous connecter pour postuler</p>")
    is_wall, reason = _detect_human_wall(page)
    assert is_wall is True
    assert reason == "login required"


def test_detect_human_wall_matches_marker_in_iframe_url_only():
    # The DOM is clean but the captcha lives in an iframe — still detected.
    page = _FakePage("<html>clean body</html>", ["https://challenges.cloudflare.com/turnstile"])
    is_wall, reason = _detect_human_wall(page)
    assert is_wall is True
    assert reason == "Cloudflare Turnstile"


# ── _is_france_travail_detail ─────────────────────────────────────────────────


@pytest.mark.parametrize("url, expected", [
    ("https://candidat.francetravail.fr/offres/recherche/detail/123", True),
    ("https://www.francetravail.fr/offres/emploi/123", True),
    ("https://example.com/apply", False),
    ("", False),
    (None, False),
])
def test_is_france_travail_detail(url, expected):
    assert _is_france_travail_detail(url) is expected
