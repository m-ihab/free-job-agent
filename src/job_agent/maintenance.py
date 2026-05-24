"""One-shot maintenance helpers exposed via the dashboard and CLI.

These migrate old data forward when the project's heuristics change:
- ``rescan_companies`` re-extracts the real employer for jobs that were saved
  while ``France Travail`` (or another aggregator) was used as the company.
- ``dedupe_jobs`` collapses jobs that became duplicates after the fingerprint
  algorithm was tightened (H/F variants, arrondissement noise).
- ``validate_cac40_sources`` probes the curated ATS slug list and marks dead
  boards in the ``broken_sources`` table so the autopilot stops trying them.
"""
from __future__ import annotations

from typing import Any

import requests

from job_agent.autopilot import CAC40_ATS_SLUGS
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.fingerprint import compute_fingerprint
from job_agent.generator.company_extract import (
    extract_real_company,
    looks_unusable_company,
)


_PROBE_URL_TEMPLATES = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
    "recruitee": "https://{slug}.recruitee.com/api/offers/",
    "workable": "https://apply.workable.com/api/v1/accounts/{slug}/jobs?limit=1",
    "personio": "https://{slug}.jobs.personio.com/xml",
}


def rescan_companies(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    """Update jobs whose company is an aggregator with the real employer name.

    Returns a small report describing what was changed.
    """
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    jobs = db.list_jobs(limit=None)
    candidates = []
    for job in jobs:
        if looks_unusable_company(job.company):
            real = extract_real_company(job)
            if real and real.casefold() != (job.company or "").casefold():
                candidates.append((job, real))
    updates: list[dict[str, str]] = []
    for job, real in candidates:
        old = job.company
        if not dry_run:
            job.company = real
            db.save_job(job)
            db.log_event(job.id, "COMPANY_RESCAN", {"old": old, "new": real})
        updates.append({"job_id": job.id, "title": job.title[:60], "old": old, "new": real})
    return {
        "checked": len(jobs),
        "updated": len(updates),
        "dry_run": dry_run,
        "updates": updates[:80],
    }


def dedupe_jobs(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    """Collapse duplicate jobs that share the new (tighter) fingerprint.

    We keep the **oldest** job (lowest ``created_at``) as the canonical record
    and delete the rest. Status/score/notes from the canonical record stay,
    so user-applied tags don't get lost.
    """
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    jobs = db.list_jobs(limit=None)
    by_fp: dict[str, list] = {}
    needs_fp: list = []
    for job in jobs:
        new_fp = compute_fingerprint(job)
        if not job.fingerprint or job.fingerprint != new_fp:
            needs_fp.append((job, new_fp))
        by_fp.setdefault(new_fp, []).append(job)
    # Apply updated fingerprints first so canonical records have stable IDs.
    if not dry_run:
        for job, new_fp in needs_fp:
            job.fingerprint = new_fp
            db.save_job(job)
    removed: list[dict[str, str]] = []
    for fingerprint, group in by_fp.items():
        if len(group) < 2:
            continue
        group_sorted = sorted(group, key=lambda j: (j.created_at or "", j.id))
        keeper = group_sorted[0]
        for victim in group_sorted[1:]:
            removed.append({
                "kept": keeper.id,
                "removed": victim.id,
                "title": victim.title[:60],
                "company": victim.company[:40],
            })
            if not dry_run:
                db.delete_job(victim.id)
                db.log_event(keeper.id, "DEDUPED", {"removed_id": victim.id})
    return {
        "checked": len(jobs),
        "fingerprints_refreshed": len(needs_fp),
        "removed": len(removed),
        "dry_run": dry_run,
        "samples": removed[:80],
    }


def validate_cac40_sources(config: AppConfig) -> dict[str, Any]:
    """Probe every (source, slug) in the CAC40 sweep list and remember which
    ones are dead. Returns a per-slug verdict (``ok`` / ``404`` / ``error``)
    plus updates the database so the autopilot stops trying dead boards.
    """
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    results: list[dict[str, Any]] = []
    healthy = 0
    broken = 0
    for source, slug, display in CAC40_ATS_SLUGS:
        template = _PROBE_URL_TEMPLATES.get(source)
        if not template:
            results.append({"source": source, "slug": slug, "display": display, "status": "unknown_source"})
            continue
        url = template.format(slug=slug)
        try:
            response = requests.get(url, timeout=10, headers={"Accept": "application/json"})
            status_code = response.status_code
            if 200 <= status_code < 300:
                db.clear_broken_source(source, slug)
                results.append({"source": source, "slug": slug, "display": display, "status": "ok", "code": status_code})
                healthy += 1
                continue
            if status_code in (404, 410, 403):
                db.mark_source_broken(source, slug, status_code=status_code, reason="probe", hours=72.0)
                broken += 1
                results.append({"source": source, "slug": slug, "display": display, "status": "dead", "code": status_code})
                continue
            results.append({"source": source, "slug": slug, "display": display, "status": "transient", "code": status_code})
        except Exception as exc:
            results.append({"source": source, "slug": slug, "display": display, "status": "error", "reason": str(exc)[:200]})
    return {
        "total": len(CAC40_ATS_SLUGS),
        "healthy": healthy,
        "broken": broken,
        "results": results,
    }


def clear_broken_sources(config: AppConfig) -> dict[str, Any]:
    """Forget all currently-broken sources so they'll be tried again."""
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    current = db.list_broken_sources()
    for entry in current:
        db.clear_broken_source(entry["source"], entry["slug"])
    return {"cleared": len(current)}
