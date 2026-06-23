"""Local-Ollama enhancement layer for outreach / LinkedIn messages.

This turns the deterministic template draft into warmer, more specific prose
*using only facts already present in the draft, profile, and job*. It is the
"Smart" engine behind the dashboard toggle; the deterministic template is both
the factual skeleton fed to the model and the guaranteed fallback.

Safety model (in order):
1. If Ollama is unreachable, return ``None`` — caller keeps the template draft.
2. The prompt forbids inventing metrics, dates, employers, or credentials.
3. Every model output is re-checked by :func:`outreach_guard.assert_grounded`;
   any violation returns ``None`` so the caller falls back to the safe draft.
"""
from __future__ import annotations

from typing import Any, Optional

from job_agent import ai_agent
from job_agent.generator.outreach_guard import assert_grounded

_CONNECT_LIMIT = 250

_KIND_TONE = {
    "connect": "a LinkedIn connection note under 250 characters, no formal opener",
    "recruiter": "a direct LinkedIn message to a recruiter, warm and specific",
    "followup": "a brief, polite follow-up message",
    "email": "a short recruiter outreach email with a subject line",
}

_PROMPT = """You rewrite a job-seeker's outreach message to sound warmer, more
specific, and more human. Return JSON only: {{"message": "..."}}.

ABSOLUTE RULES — breaking any of these makes the output unusable:
- Use ONLY facts in the DRAFT, CANDIDATE FACTS, and JOB below.
- Never invent numbers, metrics, years of experience, dates, employers, schools,
  visa/work-authorization status, certifications, awards, or patents.
- Keep the same intent and message type: {tone}.
- Do not add a signature block or contact details that are not in the draft.

CANDIDATE FACTS:
{facts}

JOB:
{job}

DRAFT:
{draft}
"""


def _facts_block(profile: Any) -> str:
    skills = []
    try:
        skills = list(profile.all_skill_names())
    except Exception:
        pass
    roles = getattr(profile, "target_roles", []) or []
    langs = getattr(profile, "languages", []) or []
    name = getattr(getattr(profile, "contact", None), "name", "") or ""
    return (f"Name: {name}\nSkills: {', '.join(skills)}\n"
            f"Target roles: {', '.join(roles)}\nLanguages: {', '.join(langs)}")


def _job_block(job: Any) -> str:
    return (f"Title: {getattr(job, 'title', '') or ''}\n"
            f"Company: {getattr(job, 'company', '') or ''}\n"
            f"Location: {getattr(job, 'location', '') or ''}\n"
            f"Tech: {', '.join(getattr(job, 'tech_stack', []) or [])}")


def enhance_message(
    draft: str,
    *,
    job: Any,
    master_cv: Any,
    profile: Any,
    kind: str = "recruiter",
    options: Any = None,
) -> Optional[str]:
    """Return a grounded, enhanced message, or ``None`` to keep the draft."""
    if not ai_agent.is_available():
        return None
    try:
        options = options or ai_agent.PolishOptions.from_env()
    except Exception:
        return None

    prompt = _PROMPT.format(
        tone=_KIND_TONE.get(kind, _KIND_TONE["recruiter"]),
        facts=_facts_block(profile),
        job=_job_block(job),
        draft=draft,
    )
    parsed = ai_agent._call_ollama_json(prompt, options, task="outreach")
    if not isinstance(parsed, dict):
        return None
    message = str(parsed.get("message") or "").strip()
    if not message:
        return None
    if kind == "connect" and len(message) > _CONNECT_LIMIT:
        return None

    ok, _violations = assert_grounded(message, draft=draft, job=job,
                                      master_cv=master_cv, profile=profile)
    if not ok:
        return None
    return message


def select_outreach_text(
    base: str,
    *,
    job: Any,
    master_cv: Any,
    profile: Any,
    kind: str = "recruiter",
    engine: str = "auto",
) -> tuple[str, str]:
    """Pick the outreach text for the requested engine.

    Returns ``(text, engine_used)`` where ``engine_used`` is ``"smart"`` only
    when a grounded Ollama enhancement was produced, otherwise ``"standard"``.
    ``engine="standard"`` skips Ollama entirely; ``"smart"``/``"auto"`` try it
    and fall back to ``base`` when unavailable or when the guard rejects output.
    """
    if str(engine or "auto").lower() == "standard":
        return base, "standard"
    enhanced = enhance_message(base, job=job, master_cv=master_cv,
                               profile=profile, kind=kind)
    if enhanced:
        return enhanced, "smart"
    return base, "standard"
