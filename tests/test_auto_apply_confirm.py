"""FILL_AND_CONFIRM must never submit without an explicit user confirmation.

Covers the confirm-timeout fall-through and the emit/clear race on the
confirmation event (bug-hunt findings #1 and #7).
"""
from __future__ import annotations

from types import SimpleNamespace

import job_agent.auto_apply as aa
from job_agent.auto_apply import ApplyMode, AutoApplySession


class FakePage:
    def __init__(self, content_html: str = "<html><form>apply</form></html>") -> None:
        self._content = content_html
        self.frames: list = []

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


def _session(monkeypatch):
    sess = AutoApplySession(config=SimpleNamespace(db_path=":memory:"), mode=ApplyMode.FILL_AND_CONFIRM)
    monkeypatch.setattr(sess, "_fill_form", lambda page, candidate, ats: (True, "filled"))
    sess.submitted_calls: list = []
    monkeypatch.setattr(sess, "_mark_submitted", lambda candidate: sess.submitted_calls.append(candidate))
    monkeypatch.setattr(aa, "_screenshot_b64", lambda page: "")
    return sess


def test_confirm_timeout_skips_and_never_submits(monkeypatch):
    """No user response within the confirmation window must mean NO submission —
    the whole point of FILL_AND_CONFIRM is that a human clicks Submit."""
    sess = _session(monkeypatch)
    sess.confirm_timeout_s = 0.05  # nobody confirms
    submit_called = []
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: submit_called.append(True) or True)

    result = sess._apply_one(FakePage(), _candidate(), 1, 1)

    assert result.status == "skipped"
    assert "time" in result.message.lower()  # explains the timeout
    assert not submit_called
    assert not sess.submitted_calls


def test_confirm_arriving_with_pending_event_is_not_lost(monkeypatch):
    """A confirm that lands the instant pending_confirm is emitted must count —
    the event must be cleared *before* the emit, not after."""
    sess = _session(monkeypatch)
    sess.confirm_timeout_s = 2.0  # generous; the confirm below should win instantly
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: True)

    original_emit = sess._emit

    def emit_and_confirm(event):
        original_emit(event)
        if event.kind == "pending_confirm":
            sess.confirm_submit()  # user clicks the moment the prompt appears

    monkeypatch.setattr(sess, "_emit", emit_and_confirm)

    result = sess._apply_one(FakePage(), _candidate(), 1, 1)

    assert result.status == "submitted"
    assert sess.submitted_calls


def test_skip_during_confirm_window_is_honored(monkeypatch):
    sess = _session(monkeypatch)
    sess.confirm_timeout_s = 2.0
    submit_called = []
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: submit_called.append(True) or True)

    original_emit = sess._emit

    def emit_and_skip(event):
        original_emit(event)
        if event.kind == "pending_confirm":
            sess.skip_current()

    monkeypatch.setattr(sess, "_emit", emit_and_skip)

    result = sess._apply_one(FakePage(), _candidate(), 1, 1)

    assert result.status == "skipped"
    assert not submit_called
    assert not sess.submitted_calls
