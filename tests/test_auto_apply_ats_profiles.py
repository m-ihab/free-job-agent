"""Tests for expanded ATS coverage: detection, per-family field synonyms,
fill routing, and structured NEEDS_MANUAL reason codes."""
from __future__ import annotations

from types import SimpleNamespace

from job_agent.auto_apply import session_actions
from job_agent.auto_apply.ats_profiles import heuristic_keys_for
from job_agent.auto_apply.detect import _detect_ats, reason_code
from job_agent.auto_apply.driver_fields import _heuristic_match
from job_agent.schemas.job import JobListing


# ---- detection ----

def test_detect_workable_urls() -> None:
    assert _detect_ats("https://apply.workable.com/acme/j/ABC123/") == "workable"
    assert _detect_ats("https://acme.workable.com/j/ABC123") == "workable"


def test_detect_existing_families_still_work() -> None:
    assert _detect_ats("https://boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert _detect_ats("https://jobs.lever.co/acme/uuid") == "lever"
    assert _detect_ats("https://jobs.smartrecruiters.com/Acme/1") == "smartrecruiters"
    assert _detect_ats("https://acme.recruitee.com/o/data-scientist") == "recruitee"
    assert _detect_ats("https://example.com/careers/apply") == "generic"


# ---- per-family heuristic tables ----

def test_heuristic_keys_for_unknown_ats_is_base_table() -> None:
    base = heuristic_keys_for("generic")
    assert "first name" in base
    assert heuristic_keys_for("does-not-exist") == base


def test_heuristic_keys_for_family_extends_base() -> None:
    workable = heuristic_keys_for("workable")
    base = heuristic_keys_for("generic")
    assert set(base).issubset(set(workable))
    assert "portfolio" in workable


def test_personio_table_covers_german_labels() -> None:
    personio = heuristic_keys_for("personio")
    assert "vorname" in personio
    assert "nachname" in personio


# ---- heuristic matching with family tables ----

def test_heuristic_match_uses_family_specific_labels() -> None:
    qa = {"first_name": "Ada", "portfolio_url": "https://ada.dev"}
    match = _heuristic_match("Vorname", qa, ats="personio")
    assert match == ("first_name", "Ada")
    match = _heuristic_match("Portfolio website", qa, ats="workable")
    assert match == ("portfolio_url", "https://ada.dev")


def test_heuristic_match_base_behaviour_unchanged() -> None:
    qa = {"email": "ada@example.com"}
    assert _heuristic_match("Email address", qa) == ("email", "ada@example.com")
    assert _heuristic_match("Completely unrelated", qa) is None


# ---- fill routing ----

class _RoutingSession:
    def __init__(self) -> None:
        self.events: list = []

    def _profile(self):
        return None

    def _emit(self, event) -> None:
        self.events.append(event)


def _candidate() -> SimpleNamespace:
    job = JobListing(title="Data Scientist", company="Acme")
    packet = SimpleNamespace(id="pkt_1", qa_answers={"email": "a@b.c"},
                             tailored_cv_pdf_path="", cover_letter_md="")
    return SimpleNamespace(job=job, packet=packet)


def test_fill_form_routes_workable_and_personio_to_standard(monkeypatch) -> None:
    routed: list[str] = []

    def _fake_standard(page, qa, cv_path, cover_md, ats="generic"):
        routed.append(ats)
        return True, "ok"

    monkeypatch.setattr(session_actions, "_fill_standard_ats", _fake_standard)
    session = _RoutingSession()
    for ats in ["workable", "personio", "greenhouse"]:
        ok, _ = session_actions.fill_form(session, page=None, candidate=_candidate(), ats=ats)
        assert ok
    assert routed == ["workable", "personio", "greenhouse"]


# ---- structured NEEDS_MANUAL reason codes ----

def test_reason_code_mapping() -> None:
    assert reason_code("reCAPTCHA") == "captcha"
    assert reason_code("hCaptcha") == "captcha"
    assert reason_code("Cloudflare Turnstile") == "anti_bot"
    assert reason_code("Cloudflare challenge") == "anti_bot"
    assert reason_code("login required") == "login_wall"
    assert reason_code("wall detection unavailable") == "detection_failed"
    assert reason_code("anything else") == "other"


def test_queue_needs_manual_emits_reason_code() -> None:
    session = _RoutingSession()
    session._mark_needs_manual = lambda candidate, reason: None
    result = session_actions.queue_needs_manual(session, _candidate(), "summary", "reCAPTCHA")
    assert result.status == "needs_manual"
    events = [e for e in session.events if e.kind == "needs_manual"]
    assert events
    assert events[0].data["reason"] == "reCAPTCHA"
    assert events[0].data["reason_code"] == "captcha"
