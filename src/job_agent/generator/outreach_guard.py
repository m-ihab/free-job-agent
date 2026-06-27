"""Honesty guard for LLM-enhanced outreach text.

The deterministic outreach templates are safe by construction: they only
interpolate real profile/job fields. The moment an LLM rewrites them for warmth
it can hallucinate metrics, years of experience, or visa/credential claims — the
exact failure mode the project forbids ("never invent candidate facts").

``assert_grounded`` compares an enhanced message against an *allowed corpus*
built from the original draft plus the real profile and job. It flags:
  * numbers that do not already appear in the source (invented metrics / years),
  * sensitive credential/authorization claims absent from the source.

It is deliberately conservative: callers treat any violation as a signal to fall
back to the deterministic draft.
"""
from __future__ import annotations

import re
from typing import Any

# Sensitive claims that must never be asserted unless they already appear in the
# candidate's own materials. Hallucinating any of these is high-risk.
_CLAIM_KEYWORDS = (
    "sponsor", "sponsorship", "visa", "work authorization", "work permit",
    "work authorisation", "citizen", "citizenship", "clearance", "phd",
    "doctorate", "patent", "award", "certified", "certification",
)

_NUMBER_RE = re.compile(r"\d+")


def _job_facts(job: Any) -> str:
    parts = [
        getattr(job, "title", "") or "",
        getattr(job, "company", "") or "",
        getattr(job, "location", "") or "",
        getattr(job, "description", "") or "",
        getattr(job, "raw_text", "") or "",
        getattr(job, "apply_url", "") or "",
        getattr(job, "source_url", "") or "",
    ]
    parts.extend(getattr(job, "tech_stack", []) or [])
    return " ".join(str(p) for p in parts)


def _profile_facts(master_cv: Any, profile: Any) -> str:
    parts: list[str] = []
    contact = getattr(profile, "contact", None)
    if contact is not None:
        parts.append(getattr(contact, "name", "") or "")
    try:
        parts.extend(profile.all_skill_names())
    except Exception:
        pass
    parts.extend(getattr(profile, "target_roles", []) or [])
    parts.extend(getattr(profile, "target_locations", []) or [])
    parts.extend(getattr(profile, "languages", []) or [])
    parts.append(getattr(profile, "summary", "") or "")
    for skill in getattr(master_cv, "skills", []) or []:
        if isinstance(skill, dict):
            parts.append(str(skill.get("name", "")))
        else:
            parts.append(str(getattr(skill, "name", "")))
    return " ".join(str(p) for p in parts)


def build_allowed_corpus(draft: str, job: Any, master_cv: Any, profile: Any) -> str:
    """Lower-cased text of everything an enhanced message is allowed to assert."""
    return " ".join([draft or "", _job_facts(job), _profile_facts(master_cv, profile)]).casefold()


def assert_grounded(
    text: str,
    *,
    draft: str,
    job: Any,
    master_cv: Any,
    profile: Any,
) -> tuple[bool, list[str]]:
    """Return ``(is_grounded, violations)`` for an enhanced outreach message.

    ``is_grounded`` is True only when ``text`` introduces no numbers or sensitive
    claims that are absent from the draft/profile/job source material.
    """
    corpus = build_allowed_corpus(draft, job, master_cv, profile)
    violations: list[str] = []

    allowed_numbers = set(_NUMBER_RE.findall(corpus))
    for number in _NUMBER_RE.findall(text or ""):
        if number not in allowed_numbers:
            violations.append(f"unsupported number '{number}'")

    lowered = (text or "").casefold()
    for keyword in _CLAIM_KEYWORDS:
        if keyword in lowered and keyword not in corpus:
            violations.append(f"unsupported claim '{keyword}'")

    # De-duplicate while preserving order for stable, readable output.
    seen: set[str] = set()
    unique: list[str] = []
    for violation in violations:
        if violation in seen:
            continue
        seen.add(violation)
        unique.append(violation)
    return (len(unique) == 0, unique)
