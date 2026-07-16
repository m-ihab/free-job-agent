"""Target-role readiness rows for the evidence-grounded skill tree."""
from __future__ import annotations

import re
from typing import Any

from job_agent.schemas.job import JobListing
from job_agent.search_quality import detect_role_family


def build_role_payloads(
    target_roles: list[str],
    jobs: list[JobListing],
    labels: dict[str, str],
    ids: dict[str, str],
    evidence_counts: dict[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role in target_roles:
        matching = _jobs_for_role(role, jobs)
        required = {
            _normalise(skill)
            for job in matching
            for skill in job.tech_stack
            if _normalise(skill)
        }
        skill_ids = [
            ids[key]
            for key in sorted(
                required, key=lambda item: (labels.get(item) or item).casefold()
            )
            if key in ids
        ]
        backed = sum(bool(evidence_counts.get(key)) for key in required)
        readiness = round(backed / len(required) * 100) if required else 0
        rows.append(
            {"role": role, "skillIds": skill_ids, "readiness": readiness}
        )
    return rows


def _jobs_for_role(role: str, jobs: list[JobListing]) -> list[JobListing]:
    role_family = detect_role_family(JobListing(title=role, company="Target role"))
    if role_family:
        return [job for job in jobs if detect_role_family(job) == role_family]
    role_key = _normalise(role)
    return [
        job
        for job in jobs
        if role_key in _normalise(job.title) or _normalise(job.title) in role_key
    ]


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", str(value).casefold()).strip()
