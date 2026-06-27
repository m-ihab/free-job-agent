"""Deterministic decision logic in the Playwright driver + session flow.

No real browser is launched. A small ``FakeElement`` / ``FakePage`` stub
returns canned values for only the methods the code under test calls.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import job_agent.auto_apply as aa
from job_agent.auto_apply import (
    ApplyMode,
    AutoApplySession,
    _build_apply_qa,
    _build_summary,
    _dedicated_browser_profile,
    _heuristic_match,
    _select_browser_profile,
    _truthy_env,
)
from job_agent.auto_apply.driver import _field_label
from job_agent.auto_apply.driver import (
    _AUTO_APPLY_PROFILE_ENV,
    _USE_REAL_CHROME_PROFILE_ENV,
    _click_submit,
    _fill_visible_fields,
)


# ── Fake Playwright primitives ────────────────────────────────────────────────


class FakeLocator:
    def __init__(self, count: int = 0, text: str = ""):
        self._count = count
        self._text = text

    def first_(self):
        return self

    @property
    def first(self):
        return self

    def count(self) -> int:
        return self._count

    def inner_text(self) -> str:
        return self._text


class FakeElement:
    """A form field stub. ``attrs`` maps attribute name -> value."""

    def __init__(self, attrs: dict[str, str] | None = None, eval_text: str = ""):
        self._attrs = attrs or {}
        self._eval_text = eval_text

    def get_attribute(self, name: str):
        return self._attrs.get(name)

    def evaluate(self, _script: str):
        return self._eval_text


class FakePage:
    """Stub that resolves <label for=...> lookups from a dict."""

    def __init__(self, labels: dict[str, str] | None = None):
        self._labels = labels or {}

    def locator(self, selector: str) -> FakeLocator:
        for key, text in self._labels.items():
            if key in selector:
                return FakeLocator(count=1, text=text)
        return FakeLocator(count=0)


class _EmptyLocator:
    @property
    def first(self):
        return self

    def count(self) -> int:
        return 0

    def is_visible(self) -> bool:
        return False

    def is_enabled(self) -> bool:
        return False


# ── _truthy_env ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value, expected", [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("maybe", False),
])
def test_truthy_env(monkeypatch, value, expected):
    monkeypatch.setenv("JOB_AGENT_TEST_FLAG", value)
    assert _truthy_env("JOB_AGENT_TEST_FLAG") is expected


def test_truthy_env_unset(monkeypatch):
    monkeypatch.delenv("JOB_AGENT_TEST_FLAG", raising=False)
    assert _truthy_env("JOB_AGENT_TEST_FLAG") is False


# ── _build_apply_qa ───────────────────────────────────────────────────────────


def _profile():
    contact = SimpleNamespace(
        name="Alice Martin",
        email="alice@example.com",
        phone="+33 6 00 00 00 00",
        linkedin_url="https://linkedin.com/in/alice",
        github_url="https://github.com/alice",
        work_authorization="EU citizen",
        location="Paris",
    )
    return SimpleNamespace(contact=contact)


def test_build_apply_qa_splits_name_and_injects_contact():
    qa = _build_apply_qa(_profile(), {})

    assert qa["first_name"] == "Alice"
    assert qa["last_name"] == "Martin"
    assert qa["full_name"] == "Alice Martin"
    assert qa["email"] == "alice@example.com"
    assert qa["city"] == "Paris"
    assert qa["work_authorization"] == "EU citizen"


def test_build_apply_qa_job_answers_override_contact():
    qa = _build_apply_qa(_profile(), {"email": "override@job.com", "why_us": "I love data"})

    assert qa["email"] == "override@job.com"  # job answer wins
    assert qa["why_us"] == "I love data"


def test_build_apply_qa_drops_empty_job_answers():
    qa = _build_apply_qa(_profile(), {"blank": "", "real": "value"})

    assert "blank" not in qa
    assert qa["real"] == "value"


def test_build_apply_qa_handles_none_profile():
    qa = _build_apply_qa(None, {"q": "a"})
    assert qa == {"q": "a"}


# ── _heuristic_match ──────────────────────────────────────────────────────────


def test_heuristic_match_maps_label_to_qa_key():
    qa = {"first_name": "Alice", "email": "a@b.com"}
    assert _heuristic_match("Your First Name", qa) == ("first_name", "Alice")


def test_heuristic_match_email_synonym():
    qa = {"email": "a@b.com"}
    assert _heuristic_match("Your email address", qa) == ("email", "a@b.com")


def test_heuristic_match_returns_none_for_unmapped_label():
    assert _heuristic_match("Favourite colour", {"first_name": "Alice"}) is None


def test_heuristic_match_skips_empty_values():
    assert _heuristic_match("First name", {"first_name": ""}) is None


# ── _field_label (priority order) ─────────────────────────────────────────────


def test_field_label_prefers_aria_label():
    field = FakeElement({"aria-label": "Email address"})
    assert _field_label(FakePage(), field) == "Email address"


def test_field_label_uses_label_for_id():
    field = FakeElement({"id": "field-1"})
    page = FakePage({"label[for='field-1']": "Phone number"})
    assert _field_label(page, field) == "Phone number"


def test_field_label_falls_back_to_placeholder():
    field = FakeElement({"placeholder": "Type your city"})
    assert _field_label(FakePage(), field) == "Type your city"


def test_field_label_normalises_name_attribute_last():
    field = FakeElement({"name": "first_name"})
    assert _field_label(FakePage(), field) == "first name"


def test_field_label_uses_autocomplete_token():
    field = FakeElement({"autocomplete": "given-name"})
    assert _field_label(FakePage(), field) == "given name"


def test_field_label_ignores_autocomplete_on_off():
    field = FakeElement({"autocomplete": "off", "name": "fallback_name"})
    assert _field_label(FakePage(), field) == "fallback name"


def test_fill_visible_fields_logs_field_failures(monkeypatch, caplog):
    class FailingField(FakeElement):
        def evaluate(self, _script: str):
            return "input"

        def fill(self, _value: str) -> None:
            raise RuntimeError("field detached")

    class FieldCollection:
        def all(self):
            return [FailingField({"type": "text"})]

    class PageWithField:
        def locator(self, _selector: str):
            return FieldCollection()

    monkeypatch.setattr(
        "job_agent.auto_apply.driver_fields._field_label",
        lambda _page, _field: "Email",
    )

    with caplog.at_level(logging.WARNING, logger="job_agent.auto_apply.driver_fields"):
        filled: list[str] = []
        _fill_visible_fields(PageWithField(), {"email": "alice@example.com"}, filled)

    assert filled == []
    assert any("Auto-apply field fill failed" in rec.message for rec in caplog.records)


def test_click_submit_logs_click_failures(caplog):
    class FailingSubmitLocator:
        @property
        def first(self):
            return self

        def count(self) -> int:
            return 1

        def is_visible(self) -> bool:
            return True

        def is_enabled(self) -> bool:
            return True

        def click(self) -> None:
            raise RuntimeError("submit intercepted")

    class PageWithFailingSubmit:
        def __init__(self):
            self.calls = 0

        def locator(self, _selector: str):
            self.calls += 1
            if self.calls == 1:
                return FailingSubmitLocator()
            return _EmptyLocator()

    with caplog.at_level(logging.WARNING, logger="job_agent.auto_apply.driver_fill"):
        assert _click_submit(PageWithFailingSubmit(), "greenhouse") is False

    assert any("Auto-apply submit click failed" in rec.message for rec in caplog.records)


# ── _build_summary ────────────────────────────────────────────────────────────


def test_build_summary_with_no_filled_fields_asks_for_manual():
    summary = _build_summary([], {"first_name": "Alice"})
    assert "manually" in summary.lower()


def test_build_summary_lists_filled_and_unmatched():
    summary = _build_summary(["Email: a@b.com"], {"work_authorization": "EU"})

    assert "Email: a@b.com" in summary
    assert "NOT auto-matched" in summary
    assert "work_authorization" in summary


# ── Browser profile selection ─────────────────────────────────────────────────


def _config(tmp_path: Path):
    return SimpleNamespace(data_dir=tmp_path / ".job_agent")


def test_dedicated_browser_profile_creates_directory(tmp_path, monkeypatch):
    monkeypatch.delenv(_AUTO_APPLY_PROFILE_ENV, raising=False)
    path = _dedicated_browser_profile(_config(tmp_path))

    assert path.exists()
    assert path.name == "auto_apply"


def test_dedicated_browser_profile_honours_env_override(tmp_path, monkeypatch):
    custom = tmp_path / "custom_profile"
    monkeypatch.setenv(_AUTO_APPLY_PROFILE_ENV, str(custom))

    path = _dedicated_browser_profile(_config(tmp_path))

    assert path == custom
    assert path.exists()


def test_select_browser_profile_defaults_to_dedicated(tmp_path, monkeypatch):
    monkeypatch.delenv(_AUTO_APPLY_PROFILE_ENV, raising=False)
    monkeypatch.delenv(_USE_REAL_CHROME_PROFILE_ENV, raising=False)

    selection = _select_browser_profile(_config(tmp_path))

    assert "dedicated" in selection.label.lower()
    assert selection.warning == ""


def test_select_browser_profile_custom_when_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv(_AUTO_APPLY_PROFILE_ENV, str(tmp_path / "mine"))

    selection = _select_browser_profile(_config(tmp_path))

    assert "custom" in selection.label.lower()


def test_select_browser_profile_real_chrome_when_unlocked(tmp_path, monkeypatch):
    monkeypatch.delenv(_AUTO_APPLY_PROFILE_ENV, raising=False)
    monkeypatch.setenv(_USE_REAL_CHROME_PROFILE_ENV, "1")
    real = tmp_path / "real_chrome"
    real.mkdir()
    monkeypatch.setattr(aa, "_find_chrome_profile", lambda: str(real))

    selection = _select_browser_profile(_config(tmp_path))

    assert selection.label == "real Chrome"
    assert selection.path == real


def test_select_browser_profile_switches_when_real_chrome_locked(tmp_path, monkeypatch):
    monkeypatch.delenv(_AUTO_APPLY_PROFILE_ENV, raising=False)
    monkeypatch.setenv(_USE_REAL_CHROME_PROFILE_ENV, "1")
    real = tmp_path / "real_chrome"
    real.mkdir()
    (real / "SingletonLock").write_text("locked")  # simulate Chrome running
    monkeypatch.setattr(aa, "_find_chrome_profile", lambda: str(real))

    selection = _select_browser_profile(_config(tmp_path))

    assert "dedicated" in selection.label.lower()
    assert selection.warning  # user is told why it switched


# ── AutoApplySession: clean form vs wall ──────────────────────────────────────


def _candidate():
    job = SimpleNamespace(id="job1", title="Data Scientist", company="ACME",
                          apply_url="https://jobs.example.com/apply")
    packet = SimpleNamespace(id="pkt1", qa_answers={}, tailored_cv_pdf_path="", cover_letter_md="")
    return SimpleNamespace(job=job, packet=packet)


class _ApplyPage:
    """A goto-capable page returning given content for wall detection."""

    def __init__(self, html: str):
        self._html = html
        self.url = "https://jobs.example.com/apply"
        self.frames = []

    def goto(self, *a, **k):
        return None

    def wait_for_timeout(self, *a, **k):
        return None

    def content(self) -> str:
        return self._html


def _session(monkeypatch, mode=ApplyMode.FULL_AUTO, fill_ok=True):
    sess = AutoApplySession(config=SimpleNamespace(db_path=":memory:"), mode=mode)
    monkeypatch.setattr(sess, "_fill_form", lambda page, candidate, ats: (fill_ok, "filled summary"))
    sess.submitted = []
    sess.manual = []
    monkeypatch.setattr(sess, "_mark_submitted", lambda c: sess.submitted.append(c))
    monkeypatch.setattr(sess, "_mark_needs_manual", lambda c, reason: sess.manual.append((c, reason)))
    monkeypatch.setattr(aa, "_screenshot_b64", lambda page: "")
    return sess


def test_full_auto_clean_form_submits(monkeypatch):
    sess = _session(monkeypatch)
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: True)

    result = sess._apply_one(_ApplyPage("<form>clean</form>"), _candidate(), 1, 1)

    assert result.status == "submitted"
    assert sess.submitted and not sess.manual


def test_full_auto_wall_queues_needs_manual_without_blocking(monkeypatch):
    sess = _session(monkeypatch)
    submit_calls: list = []
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: submit_calls.append(1) or True)

    result = sess._apply_one(_ApplyPage("<div class='g-recaptcha'></div>"), _candidate(), 1, 1)

    assert result.status == "needs_manual"
    assert "reCAPTCHA" in result.message
    assert sess.manual and not submit_calls  # detected, never submitted


def test_full_auto_unfillable_clean_form_is_error(monkeypatch):
    sess = _session(monkeypatch, fill_ok=False)
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: True)

    result = sess._apply_one(_ApplyPage("<form>clean</form>"), _candidate(), 1, 1)

    assert result.status == "error"
    assert not sess.manual


def test_full_auto_cancel_skips_before_submit(monkeypatch):
    sess = _session(monkeypatch)
    sess._cancel_flag = True
    monkeypatch.setattr(aa, "_click_submit", lambda page, ats: True)

    result = sess._apply_one(_ApplyPage("<form>clean</form>"), _candidate(), 1, 1)

    assert result.status == "skipped"
    assert not sess.submitted


# ── get_candidates_preview ────────────────────────────────────────────────────


def test_get_candidates_preview_returns_plain_dicts(monkeypatch):
    cand = _candidate()
    cand.packet.fit_score = 82.0
    cand.job.location = "Paris"
    monkeypatch.setattr(aa, "get_ready_candidates", lambda min_score, limit: [cand])

    preview = aa.get_candidates_preview(min_score=70, limit=5)

    assert preview == [{
        "job_id": "job1",
        "title": "Data Scientist",
        "company": "ACME",
        "location": "Paris",
        "apply_url": "https://jobs.example.com/apply",
        "packet_id": "pkt1",
        "fit_score": 82.0,
    }]
