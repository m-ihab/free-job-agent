"""Recruiter-facing proof pack grounded in preflight evidence."""
from __future__ import annotations

from job_agent.generator.preflight import PreflightResult
from job_agent.schemas.job import JobListing


def render_proof_pack_markdown(job: JobListing, preflight: PreflightResult) -> str:
    lines = [
        f"# Proof Pack - {job.title} at {job.company}",
        "",
        "## Fit Snapshot",
        f"- Verdict: {preflight.verdict}",
        f"- Fit score: {preflight.fit_score}/100",
        f"- Must-have coverage: {round(preflight.must_have_coverage * 100)}%",
        f"- ATS keyword coverage: {round(preflight.keyword_coverage * 100)}%",
        f"- Recruiter confidence: {round(preflight.recruiter_confidence * 100)}%",
        "",
        "## Evidence-backed strengths",
    ]
    lines.extend(_evidence_lines(preflight))
    lines.extend(["", "## Safe keywords to emphasize"])
    lines.extend(_bullet_list(preflight.safe_keywords_to_add, "No extra safe keyword suggestions."))
    lines.extend(["", "## Missing or weak must-haves"])
    lines.extend(_bullet_list(preflight.missing_must_haves, "No major must-have gaps detected."))
    lines.extend(["", "## Unsupported claims to avoid"])
    lines.extend(_bullet_list(preflight.unsafe_claims_to_avoid, "No unsafe keyword claims detected."))
    lines.extend(
        [
            "",
            "## Manual-use rules",
            "- Use this page to prepare interviews, referral asks, and recruiter calls.",
            "- Do not add metrics, certifications, dates, or work-authorization claims unless they exist in the evidence above.",
            "- If a missing requirement is factual but true, add it to the local profile/evidence first, then regenerate.",
            "",
        ]
    )
    return "\n".join(lines)


def _evidence_lines(preflight: PreflightResult) -> list[str]:
    if not preflight.best_evidence_items:
        return ["- No local evidence item matched strongly enough yet."]
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for item in preflight.best_evidence_items[:8]:
        key = (item.kind, item.label)
        if key in seen:
            continue
        seen.add(key)
        source = f" ({item.source_ref})" if item.source_ref else ""
        value = f": {item.value}" if item.value else ""
        lines.append(f"- {item.kind}: {item.label}{value}{source}")
    return lines


def _bullet_list(items: list[str], empty: str) -> list[str]:
    values = [item for item in items if item]
    return [f"- {item}" for item in values] if values else [f"- {empty}"]
