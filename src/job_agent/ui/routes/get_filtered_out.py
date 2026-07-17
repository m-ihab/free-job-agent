"""Read-only dashboard route explaining hard-filter and search-noise rejections."""

from __future__ import annotations

from collections import Counter
from typing import Any

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.filters import FilterConfig, apply_filters
from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.search_quality import assess_search_quality
from job_agent.validators import load_profile_bundle


_RULE_LABELS = {
    "blocked_company": "Blocked company",
    "blocked_keyword": "Blocked keyword",
    "missing_required_keyword": "Missing required keyword",
    "salary_too_low": "Salary too low",
    "not_remote": "Not remote",
    "location_not_allowed": "Location not allowed",
    "job_type_not_allowed": "Job type not allowed",
    "sponsorship_gated": "Sponsorship gated",
}

_NOISE_LABELS = {
    "generic-data-title": "Generic data title",
    "off-topic-title": "Off-topic title",
    "outside-target-region": "Outside target region",
    "seniority-or-degree-barrier": "Seniority or degree barrier",
}


def _noise_reasons(job: JobListing) -> list[tuple[str, str]]:
    quality = assess_search_quality(job, query="data scientist", location=job.location or "")
    if bool(quality.get("relevant")):
        return []
    flags = [str(flag) for flag in quality.get("flags", [])]
    if flags:
        return [
            (f"search_{flag.replace('-', '_')}", _NOISE_LABELS.get(flag, flag.replace("-", " ").title()))
            for flag in flags
        ]
    return [
        (
            "search_low_relevance",
            f"Low search quality (score {int(quality.get('score', 0))})",
        )
    ]


def _job_reasons(
    job: JobListing, profile: CandidateProfile | None
) -> list[tuple[str, str]]:
    result = apply_filters(job, FilterConfig(), profile)
    hard_reasons = list(zip(result.reason_codes, result.reasons))
    combined = [*hard_reasons, *_noise_reasons(job)]
    return list(dict.fromkeys(combined))


def _load_profile(config: AppConfig) -> CandidateProfile | None:
    try:
        profile, _master_cv, _qa_profile = load_profile_bundle(config)
        return profile
    except (OSError, ValueError):
        return None


def build_filtered_out(config: AppConfig) -> dict[str, Any]:
    """Evaluate current DB rows without mutating jobs, packets, or evidence."""
    db = Database(config.db_path)  # type: ignore[arg-type]
    all_jobs = db.list_jobs(limit=None)
    jobs = [job for job in all_jobs if job.status is JobStatus.FILTERED]
    profile = _load_profile(config)
    counts: Counter[str] = Counter()
    filtered: list[dict[str, Any]] = []
    for job in jobs:
        reasons = _job_reasons(job, profile) or [
            ("filtered_status", "Previously filtered out")
        ]
        counts.update({rule for rule, _message in reasons})
        filtered.append(
            {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "source": job.source,
                "reason": "; ".join(message for _rule, message in reasons),
                "reasons": [
                    {"rule": rule, "message": message} for rule, message in reasons
                ],
            }
        )
    rules = [
        {
            "rule": rule,
            "label": _RULE_LABELS.get(rule, rule.removeprefix("search_").replace("_", " ").title()),
            "count": count,
        }
        for rule, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "evaluated_count": len(all_jobs),
        "filtered_count": len(filtered),
        "passed_count": len(all_jobs) - len(filtered),
        "rule_counts": dict(counts),
        "rules": rules,
        "jobs": filtered,
    }


def get_filtered_out(h: Any) -> None:
    h._send_json(build_filtered_out(h._config()))
