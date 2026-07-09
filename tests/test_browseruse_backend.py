"""Tests for the experimental browser-use fill backend (contract-first)."""
from __future__ import annotations

import job_agent.auto_apply.browseruse_backend as bub
from job_agent.auto_apply.session_types import ApplyMode


FIELDS = {"First Name": "Mo", "Email": "mo@example.org"}


def _plan(sample_job):
    plan, reason = bub.build_fill_plan(sample_job, "pkt-1", FIELDS)
    assert reason == ""
    return plan


# ── plan building (grounding + secret hygiene) ────────────────────────────────


def test_plan_requires_apply_url(sample_job):
    sample_job.apply_url = None
    plan, reason = bub.build_fill_plan(sample_job, "pkt-1", FIELDS)
    assert plan is None
    assert reason == "missing_apply_url"


def test_plan_requires_grounded_values(sample_job):
    plan, reason = bub.build_fill_plan(sample_job, "pkt-1", {})
    assert plan is None
    assert reason == "no_grounded_field_values"


def test_plan_never_leaks_values_into_prompt(sample_job):
    plan = _plan(sample_job)
    assert "Mo" not in plan.task_prompt
    assert "mo@example.org" not in plan.task_prompt
    assert "x_first_name" in plan.task_prompt
    assert plan.sensitive_data["x_email"] == "mo@example.org"


def test_plan_forbids_submitting_and_bypassing(sample_job):
    prompt = _plan(sample_job).task_prompt.lower()
    assert "do not click submit" in prompt
    assert "captcha" in prompt
    assert "needs_manual" in prompt
    assert "never invent" in prompt


def test_plan_locks_domains_to_apply_host(sample_job):
    plan = _plan(sample_job)
    assert "example.com" in plan.allowed_domains
    assert "www.example.com" in plan.allowed_domains


# ── run contract ──────────────────────────────────────────────────────────────


def test_full_auto_is_refused(sample_job):
    outcome = bub.run_fill(_plan(sample_job), ApplyMode.FULL_AUTO)
    assert outcome.status == "needs_manual"
    assert outcome.reason_code == "browseruse_fullauto_disabled"


def test_unavailable_without_library(monkeypatch, sample_job):
    monkeypatch.setattr(bub, "is_browseruse_available", lambda: False)
    outcome = bub.run_fill(_plan(sample_job), ApplyMode.FILL_AND_CONFIRM)
    assert outcome.status == "unavailable"
    assert "browseruse" in outcome.message


def test_successful_fill_awaits_human_confirm(sample_job):
    outcome = bub.run_fill(
        _plan(sample_job), ApplyMode.FILL_AND_CONFIRM,
        execute=lambda plan, headless: "FILLED",
    )
    assert outcome.status == "filled_pending_confirm"
    kinds = [event.kind for event in outcome.events]
    assert kinds == ["progress", "pending_confirm"]


def test_agent_reported_wall_maps_to_needs_manual(sample_job):
    outcome = bub.run_fill(
        _plan(sample_job), ApplyMode.FILL_AND_CONFIRM,
        execute=lambda plan, headless: "NEEDS_MANUAL: hCaptcha on final step",
    )
    assert outcome.status == "needs_manual"
    assert "hCaptcha" in outcome.message
    assert outcome.events[-1].kind == "needs_manual"


def test_execution_error_never_raises(sample_job):
    def _boom(plan, headless):
        raise RuntimeError("chrome crashed")

    outcome = bub.run_fill(_plan(sample_job), ApplyMode.FILL_AND_CONFIRM, execute=_boom)
    assert outcome.status == "error"
    assert outcome.reason_code == "RuntimeError"


def test_audit_payload_is_complete_and_value_free(sample_job):
    plan = _plan(sample_job)
    outcome = bub.run_fill(plan, ApplyMode.FILL_AND_CONFIRM, execute=lambda p, h: "FILLED")
    payload = bub.attempt_audit_payload(plan, outcome)
    assert payload["backend"] == "browser_use"
    assert payload["status"] == "filled_pending_confirm"
    assert payload["fields"] == ["x_email", "x_first_name"]
    assert "mo@example.org" not in str(payload)  # audit log stays PII-light
