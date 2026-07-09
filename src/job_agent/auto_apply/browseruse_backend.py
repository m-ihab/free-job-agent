"""Experimental browser-use fill backend for ATS families without profiles.

Scope contract (v1, deliberately conservative):
  * FILL_AND_CONFIRM only — the agent fills, the human reviews and submits.
    FULL_AUTO requests are refused with ``needs_manual`` until this backend has
    a supervised track record (the report's "FILL_AND_CONFIRM first" gate).
  * Grounding: values come ONLY from the caller-provided ``field_values`` map
    (evidence-store backed). The task prompt references placeholders; real
    values travel via browser-use's ``sensitive_data`` channel and never appear
    in the prompt. Unknown required fields are left blank → NEEDS_MANUAL.
  * Never bypasses CAPTCHAs / logins / anti-bot walls: the agent is instructed
    to stop and report, which maps to the standard NEEDS_MANUAL handoff.

The heavy dependency is optional: ``pip install 'free-job-agent[browseruse]'``.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from job_agent.auto_apply.session_types import ApplyEvent, ApplyMode
from job_agent.schemas.job import JobListing

logger = logging.getLogger(__name__)

_NEEDS_MANUAL_MARK = "NEEDS_MANUAL"

_TASK_TEMPLATE = """Open {apply_url} and fill the job application form.

Fill ONLY these fields, using exactly these placeholder values (they will be
substituted securely): {placeholder_lines}

Strict rules:
- Never invent, guess, or autofill any value that is not listed above.
- If a REQUIRED form field is not covered by the list, or the page shows a
  CAPTCHA, login wall, or any anti-bot check, STOP immediately and reply
  starting with "{mark}: <short reason>". Do not try to get around it.
- Do NOT click Submit / Send / Postuler / Envoyer or any final submission
  button. Stop once every listed field is filled and reply "FILLED".
"""


@dataclass(frozen=True)
class BrowserUseFillPlan:
    """Everything needed to run one grounded fill attempt."""

    job_id: str
    packet_id: str
    apply_url: str
    allowed_domains: tuple[str, ...]
    task_prompt: str
    sensitive_data: dict[str, str]
    cv_path: str | None = None


@dataclass(frozen=True)
class BrowserUseFillOutcome:
    """Audit-ready outcome; the session layer logs it via ``db.log_event``."""

    status: str  # filled_pending_confirm | needs_manual | error | unavailable
    reason_code: str = ""
    message: str = ""
    events: tuple[ApplyEvent, ...] = field(default_factory=tuple)


def _load_browser_use():
    """Import seam so tests can simulate the library being absent/present."""
    try:
        import browser_use  # type: ignore

        return browser_use
    except Exception:
        return None


def is_browseruse_available() -> bool:
    return _load_browser_use() is not None


def _domains_for(apply_url: str) -> tuple[str, ...]:
    host = urlparse(apply_url).netloc.split(":")[0].lower()
    if not host:
        return ()
    bare = host[4:] if host.startswith("www.") else host
    return tuple(dict.fromkeys((host, bare, f"www.{bare}")))


def build_fill_plan(
    job: JobListing,
    packet_id: str,
    field_values: dict[str, str],
    *,
    cv_path: str | None = None,
) -> tuple[BrowserUseFillPlan | None, str]:
    """Build a grounded fill plan. Returns (None, reason) when impossible."""
    if not job.apply_url:
        return None, "missing_apply_url"
    clean = {k.strip(): v for k, v in (field_values or {}).items() if k.strip() and str(v).strip()}
    if not clean:
        return None, "no_grounded_field_values"
    placeholders = {f"x_{re.sub(r'[^a-z0-9]+', '_', key.lower())}": str(value) for key, value in clean.items()}
    lines = "".join(f"\n  - {key} -> {ph}" for (key, _), ph in zip(clean.items(), placeholders))
    prompt = _TASK_TEMPLATE.format(
        apply_url=job.apply_url, placeholder_lines=lines, mark=_NEEDS_MANUAL_MARK
    )
    return (
        BrowserUseFillPlan(
            job_id=job.id,
            packet_id=packet_id,
            apply_url=job.apply_url,
            allowed_domains=_domains_for(job.apply_url),
            task_prompt=prompt,
            sensitive_data=placeholders,
            cv_path=cv_path,
        ),
        "",
    )


def _execute_agent(plan: BrowserUseFillPlan, headless: bool) -> str:
    """Run the browser-use agent. Separated as an injectable seam for tests."""
    browser_use = _load_browser_use()
    if browser_use is None:  # pragma: no cover - guarded by caller
        raise RuntimeError("browser_use not installed")
    from job_agent.polish import PolishOptions, resolve_ollama_model

    try:
        llm_cls: Any = getattr(browser_use, "ChatOllama", None)
        if llm_cls is None:
            from browser_use.llm import ChatOllama  # type: ignore[import-not-found]

            llm_cls = ChatOllama
        llm = llm_cls(model=resolve_ollama_model(PolishOptions.from_env()))
    except Exception as exc:
        raise RuntimeError(f"no local llm for browser_use: {exc}") from exc

    async def _run() -> str:
        agent = browser_use.Agent(
            task=plan.task_prompt,
            llm=llm,
            sensitive_data=dict(plan.sensitive_data),
        )
        history = await agent.run()
        final = getattr(history, "final_result", None)
        return str(final() if callable(final) else final or "")

    return asyncio.run(_run())


def run_fill(
    plan: BrowserUseFillPlan,
    mode: ApplyMode,
    *,
    headless: bool = False,
    execute=None,
) -> BrowserUseFillOutcome:
    """Execute one fill attempt under the apply-mode contract. Never raises."""

    def _event(kind: str, message: str) -> ApplyEvent:
        return ApplyEvent(kind, job_id=plan.job_id, packet_id=plan.packet_id, message=message)

    if mode == ApplyMode.FULL_AUTO:
        return BrowserUseFillOutcome(
            status="needs_manual",
            reason_code="browseruse_fullauto_disabled",
            message="browser-use backend is FILL_AND_CONFIRM-only until supervised runs prove it",
            events=(_event("needs_manual", "browser-use refused FULL_AUTO (experimental backend)"),),
        )
    if execute is None and not is_browseruse_available():
        return BrowserUseFillOutcome(
            status="unavailable",
            reason_code="browser_use_not_installed",
            message="install with: pip install 'free-job-agent[browseruse]'",
        )
    runner = execute or _execute_agent
    started = (_event("progress", f"browser-use fill started for {plan.apply_url}"),)
    try:
        result_text = str(runner(plan, headless) or "")
    except Exception as exc:
        logger.warning("browser-use fill failed for %s: %s", plan.job_id, exc)
        return BrowserUseFillOutcome(
            status="error",
            reason_code=type(exc).__name__,
            message=str(exc),
            events=started + (_event("error", f"browser-use error: {exc}"),),
        )
    if _NEEDS_MANUAL_MARK in result_text.upper():
        reason = result_text.split(":", 1)[1].strip() if ":" in result_text else "agent reported a wall"
        return BrowserUseFillOutcome(
            status="needs_manual",
            reason_code="agent_reported_wall",
            message=reason,
            events=started + (_event("needs_manual", reason),),
        )
    return BrowserUseFillOutcome(
        status="filled_pending_confirm",
        message="form filled; review and submit manually",
        events=started + (_event("pending_confirm", "browser-use filled the form; awaiting human review"),),
    )


def attempt_audit_payload(plan: BrowserUseFillPlan, outcome: BrowserUseFillOutcome) -> dict:
    """Stable payload for ``db.log_event`` so every attempt stays auditable."""
    return {
        "backend": "browser_use",
        "packet_id": plan.packet_id,
        "apply_url": plan.apply_url,
        "status": outcome.status,
        "reason_code": outcome.reason_code,
        "message": outcome.message[:500],
        "fields": sorted(plan.sensitive_data),
    }
