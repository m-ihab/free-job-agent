"""FULL_AUTO is genuinely hands-off and never blocks; walls are detected, not bypassed."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import job_agent.auto_apply as aa
from job_agent.auto_apply import ApplyMode, AutoApplySession, _detect_human_wall


class FakePage:
    def __init__(self, content_html: str, frame_urls: list[str] | None = None) -> None:
        self._content = content_html
        self.frames = [SimpleNamespace(url=u) for u in (frame_urls or [])]

    def goto(self, *a, **k):
        return None

    def wait_for_timeout(self, *a, **k):
        return None

    def content(self) -> str:
        return self._content


def _candidate():
    job = SimpleNamespace(id="job1", title="Data Scientist", company="ACME",
                          apply_url="https://jobs.example.com/apply")
    packet = SimpleNamespace(id="pkt1", qa_answers={}, tailored_cv_pdf_path="", cover_letter_md="")
    return SimpleNamespace(job=job, packet=packet)


def _session(monkeypatch, *, fill_ok: bool = True):
    sess = AutoApplySession(config=SimpleNamespace(db_path=":memory:"), mode=ApplyMode.FULL_AUTO)
    monkeypatch.setattr(sess, "_fill_form", lambda page, candidate, ats: (fill_ok, "filled"))
    sess.submitted_calls: list = []
    sess.manual_calls: list = []
    monkeypatch.setattr(sess, "_mark_submitted", lambda candidate: sess.submitted_calls.append(candidate))
    monkeypatch.setattr(sess, "_mark_needs_manual", lambda candidate, reason: sess.manual_calls.append((candidate, reason)))
    monkeypatch.setattr(aa, "_screenshot_b64", lambda page: "")
    return sess


# ── Wall detection (detection only) ──────────────────────────────────────────

@pytest.mark.parametrize(
    "html, frames, expected",
    [
        ("<html><div class='g-recaptcha'></div></html>", [], "reCAPTCHA"),
        ("<html>ok</html>", ["https://hcaptcha.com/captcha"], "hCaptcha"),
        ("<html>Checking your browser before accessing</html>", [], "Cloudflare challenge"),
        ("<html>Please log in to continue</html>", [], "login required"),
    ],
)
def test_detect_human_wall_positive(html, frames, expected):
    is_wall, reason = _detect_human_wall(FakePage(html, frames))
    assert is_wall and reason == expected


def test_detect_human_wall_negative():
    assert _detect_human_wall(FakePage("<html><form>name email</form></html>")) == (False, "")


# ── FULL_AUTO behavior ───────────────────────────────────────────────────────

def test_full_auto_submits_clean_form_without_blocking(monkeypatch):
    sess = _session(monkeypatch)
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: True)
    page = FakePage("<html><form>apply</form></html>")
    result = sess._apply_one(page, _candidate(), 1, 1)
    assert result.status == "submitted"
    assert sess.submitted_calls and not sess.manual_calls


def test_full_auto_queues_wall_and_does_not_submit(monkeypatch):
    sess = _session(monkeypatch)
    submit_called = []
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: submit_called.append(True) or True)
    page = FakePage("<html><div class='g-recaptcha'></div></html>")
    result = sess._apply_one(page, _candidate(), 1, 1)
    assert result.status == "needs_manual"
    assert "reCAPTCHA" in result.message
    assert sess.manual_calls and not submit_called  # detected, never submitted


def test_full_auto_unfillable_with_wall_is_queued_not_errored(monkeypatch):
    sess = _session(monkeypatch, fill_ok=False)
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: True)
    page = FakePage("<html>Please log in to continue</html>")
    result = sess._apply_one(page, _candidate(), 1, 1)
    assert result.status == "needs_manual"


def test_full_auto_post_submit_wall_hands_off(monkeypatch):
    """A wall that appears *after* the submit click must trigger a hand-off, not
    a false 'submitted' record (finding 4)."""
    sess = _session(monkeypatch)

    def submit(page, ats):
        page._content = "<html><div class='g-recaptcha'></div></html>"  # wall after submit
        return True

    monkeypatch.setattr(aa, "_click_submit", submit)
    page = FakePage("<html><form>apply</form></html>")  # clean before submit
    result = sess._apply_one(page, _candidate(), 1, 1)
    assert result.status == "needs_manual"
    assert sess.manual_calls and not sess.submitted_calls  # not falsely submitted


def test_full_auto_detection_failure_fails_closed(monkeypatch):
    """If the page cannot be inspected, FULL_AUTO must hand off (fail closed),
    never submit blind (finding 6)."""
    sess = _session(monkeypatch)
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: True)

    class Unreadable(FakePage):
        def content(self):
            raise RuntimeError("navigation in progress")

    result = sess._apply_one(Unreadable(""), _candidate(), 1, 1)
    assert result.status == "needs_manual"
    assert not sess.submitted_calls


def test_full_auto_queue_persistence_failure_surfaces_error(monkeypatch):
    """If persisting the NEEDS_MANUAL hand-off fails, the result must be an error
    (not a clean 'needs_manual'), so the job is not silently dropped (finding 7)."""
    sess = _session(monkeypatch)

    def boom(candidate, reason):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(sess, "_mark_needs_manual", boom)
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: True)
    page = FakePage("<html><div class='g-recaptcha'></div></html>")  # wall pre-submit
    result = sess._apply_one(page, _candidate(), 1, 1)
    assert result.status == "error"
    assert "not queued" in result.message.lower()
    assert not sess.submitted_calls
