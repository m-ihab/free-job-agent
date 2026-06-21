"""Shared module-level helpers for the dashboard HTTP routes.

These were extracted verbatim from ``job_agent.ui.server`` so the route modules
under ``job_agent.ui.routes`` can import them without creating a circular import
(``server`` imports the route registries from ``routes``; ``routes`` must never
import ``server``). ``server`` re-imports these names for backward compatibility.
"""
from __future__ import annotations

import json
import logging
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.enrichment import EnrichOptions, enrich_job
from job_agent.exporters.internship_workbook import export_applied_internships
from job_agent.ai_agent import suggest_search_queries
from job_agent.intake.free_apis import (
    KEYWORD_ONLY_SOURCES,
    search_all_free_sources,
    search_free_api_jobs,
)
from job_agent.pipeline import add_job_to_tracker, generate_packet_for_job
from job_agent.schemas.job import JobStatus
from job_agent.timeutil import utc_now
from job_agent.tracker import ApplicationTracker
from job_agent.ui.services import (
    build_manual_search_groups,
    is_france_travail_configured,
    job_to_dict,
)
from job_agent.validators import load_profile_bundle

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).with_name("static")


def _tracker(config: AppConfig) -> ApplicationTracker:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    return ApplicationTracker(db)


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def _safe_int(value: object, default: int, minimum: int = 1, maximum: int = 100) -> int:
    try:
        parsed = int(value)  # type: ignore[call-overload]  # value is validated by the except
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _file_response_path(config: AppConfig, raw_path: str) -> Path | None:
    try:
        candidate = Path(raw_path).expanduser().resolve()
    except Exception:
        return None
    roots = [config.data_dir, config.outputs_dir, config.profiles_dir]
    for root in roots:
        if root is None:
            continue
        try:
            candidate.relative_to(Path(root).resolve())
            return candidate if candidate.exists() and candidate.is_file() else None
        except ValueError:
            continue
    return None


def _latest_packet_for_job(db: Database, job_id: str):
    packets = db.get_packets_for_job(job_id)
    return packets[0] if packets else None


# GitHub usernames: alphanumeric or hyphen, 1–39 chars, not starting with hyphen.
_GITHUB_HANDLE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def _resolve_github_handle(config: AppConfig, payload: dict) -> str:
    """Resolve a GitHub handle from the request or the saved profile.

    The handle is sanitized to GitHub's allowed charset so it cannot inject
    extra path/query segments into the ``api.github.com`` URLs built downstream.
    Returns ``""`` when absent or invalid.
    """
    handle = str(payload.get("handle") or "").strip()
    if not handle and config.profiles_dir:
        try:
            data = json.loads((config.profiles_dir / "candidate_profile.json").read_text(encoding="utf-8"))
            url = (data.get("contact") or {}).get("github_url") or ""
            handle = url.rstrip("/").rsplit("/", 1)[-1] if url else ""
        except (OSError, ValueError) as exc:
            logger.debug("Could not read github_url from profile: %s", exc)
            handle = ""
    handle = handle.strip().lstrip("@")
    return handle if _GITHUB_HANDLE_RE.match(handle) else ""


def _list_jobs(config: AppConfig, status: str = "") -> list[dict]:
    """Fetch all jobs + their enrichments / AI cache / latest packet in 4 queries
    instead of N*3 — significantly faster on databases with 50+ jobs.

    No row cap: the dashboard shows the full tracked set (the badge/metrics count
    these), not just the most recent 100.
    """
    tracker = _tracker(config)
    status_filter = JobStatus(status) if status else None
    jobs = tracker.list_jobs(status=status_filter, limit=None)
    if not jobs:
        return []
    job_ids = [job.id for job in jobs]
    enrichments = tracker.db.bulk_get_enrichments(job_ids)
    ai_caches = tracker.db.bulk_list_ai_cache(job_ids)
    latest_packets = tracker.db.bulk_latest_packets(job_ids)
    results: list[dict] = []
    for job in jobs:
        results.append(job_to_dict(
            job,
            latest_packets.get(job.id),
            enrichment=enrichments.get(job.id),
            ai_cache=ai_caches.get(job.id, {}),
        ))
    return results


def _needs_manual_jobs(config: AppConfig) -> list[dict]:
    """NEEDS_MANUAL jobs plus the wall reason from their latest hand-off event.

    Full-auto logs a ``NEEDS_MANUAL`` event (with the detected wall reason) when
    it queues a job, so the dashboard queue can show *why* each one needs a human
    instead of just listing them.
    """
    jobs = _list_jobs(config, status=JobStatus.NEEDS_MANUAL.value)
    if not jobs:
        return jobs
    db = _tracker(config).db
    for job in jobs:
        reason = ""
        for event in db.get_events(job["id"]):
            if event.get("event_type") == "NEEDS_MANUAL":
                reason = str((event.get("event_data") or {}).get("reason") or "")
        job["needs_manual_reason"] = reason
    return jobs


def _search_links(payload: dict) -> dict:
    query = str(payload.get("query") or "data scientist")
    location = str(payload.get("location") or "Paris")
    language = str(payload.get("language") or "both")
    boards = str(payload.get("boards") or "recommended")
    limit = _safe_int(payload.get("limit"), 8, maximum=30)
    groups = build_manual_search_groups(query, location, language, limit, boards)
    link_count = sum(len(group["links"]) for group in groups)
    return {"groups": groups, "query_count": len(groups), "link_count": link_count, "generated_at": utc_now()}


def _save_jobs(config: AppConfig, jobs, *, prepare_packets: bool, force_packets: bool) -> dict:
    saved: list[dict] = []
    imported = duplicates = prepared = 0
    failures: list[str] = []
    tracker = _tracker(config)
    for job in jobs:
        tracked, created = add_job_to_tracker(config, job)
        if created:
            imported += 1
        else:
            duplicates += 1
        packet = None
        if prepare_packets and created:
            try:
                packet = generate_packet_for_job(config, tracked.id, force=force_packets)
                prepared += 1
            except Exception as exc:
                failures.append(f"{tracked.title} @ {tracked.company}: {exc}")
        else:
            packet = _latest_packet_for_job(tracker.db, tracked.id)
        saved.append(job_to_dict(tracked, packet))
    return {"jobs": saved, "imported": imported, "duplicates": duplicates, "prepared": prepared, "failures": failures}


def _enrich_batch(config: AppConfig, payload: dict) -> dict:
    job_ids = payload.get("job_ids") or []
    results: list[dict] = []
    options = EnrichOptions(
        rome=bool(payload.get("rome", True)),
        anotea=bool(payload.get("anotea", True)),
        training=bool(payload.get("training", True)),
        labour_market=bool(payload.get("labour_market", True)),
        territory=bool(payload.get("territory", True)),
        employer=bool(payload.get("employer", True)),
        other=bool(payload.get("other", True)),
    )
    for job_id in job_ids:
        try:
            report = enrich_job(config, str(job_id), options)
            results.append({"job_id": job_id, "ok": True, "sources": report.get("sources")})
        except Exception as exc:
            results.append({"job_id": job_id, "ok": False, "error": str(exc)})
    return {"count": len(results), "results": results}


def _multi_source_search(config: AppConfig, payload: dict) -> dict:
    query = str(payload.get("query") or "")
    location = str(payload.get("location") or "")
    limit_per_source = _safe_int(payload.get("limit_per_source"), 8, maximum=30)
    sources_raw = payload.get("sources")
    if isinstance(sources_raw, str):
        sources = [s.strip() for s in sources_raw.split(",") if s.strip()]
    elif isinstance(sources_raw, list):
        sources = [str(s).strip() for s in sources_raw if str(s).strip()]
    else:
        sources = list(KEYWORD_ONLY_SOURCES)
    save = bool(payload.get("save", True))
    prepare_packets = bool(payload.get("prepare_packets", False))
    force_packets = bool(payload.get("force_packets", False))
    internships_only = bool(payload.get("internships_only", False))
    remote_only = bool(payload.get("remote_only", False))
    # Floor relevance at 20 so a multi-token query (e.g. "stage data") can't admit
    # jobs that match only one weak token. Callers can raise it, never lower it.
    min_relevance = _safe_int(payload.get("min_relevance"), 20, minimum=20, maximum=100)
    france_eu_only = bool(payload.get("france_eu_only", False))
    radius_km = _safe_int(payload.get("radius_km"), 0, minimum=0, maximum=100)
    aggregate = search_all_free_sources(
        query=query,
        location=location,
        limit_per_source=limit_per_source,
        sources=sources,
        remote_only=remote_only,
        internships_only=internships_only,
        min_relevance=min_relevance,
        france_eu_only=france_eu_only,
        radius_km=radius_km,
        use_cache=True,
        cache_ttl_hours=6.0,
    )
    if save:
        save_result = _save_jobs(config, aggregate["jobs"], prepare_packets=prepare_packets, force_packets=force_packets)
    else:
        save_result = {
            "jobs": [job_to_dict(job) for job in aggregate["jobs"]],
            "imported": 0,
            "duplicates": 0,
            "prepared": 0,
            "failures": [],
        }
    save_result.update({
        "per_source": aggregate["per_source"],
        "errors": aggregate["errors"],
        "found": len(aggregate["jobs"]),
        "sources": sources,
    })
    return save_result


def _api_search(config: AppConfig, payload: dict) -> dict:
    source = str(payload.get("source") or "francetravail")
    query = str(payload.get("query") or "data scientist")
    location = str(payload.get("location") or "Paris")
    limit = _safe_int(payload.get("limit"), 10, maximum=50)
    save = bool(payload.get("save", True))
    prepare_packets = bool(payload.get("prepare_packets", False))
    force_packets = bool(payload.get("force_packets", False))
    internships_only = bool(payload.get("internships_only", False))
    # Floor relevance at 20 so a multi-token query (e.g. "stage data") can't admit
    # jobs that match only one weak token. Callers can raise it, never lower it.
    min_relevance = _safe_int(payload.get("min_relevance"), 20, minimum=20, maximum=100)
    france_eu_only = bool(payload.get("france_eu_only", False))
    radius_km = _safe_int(payload.get("radius_km"), 0, minimum=0, maximum=100)
    jobs = search_free_api_jobs(
        source,
        query=query,
        location=location,
        limit=limit,
        internships_only=internships_only,
        min_relevance=min_relevance,
        france_eu_only=france_eu_only,
        radius_km=radius_km,
        use_cache=True,
        cache_ttl_hours=6.0,
    )
    if save:
        result = _save_jobs(config, jobs, prepare_packets=prepare_packets, force_packets=force_packets)
    else:
        result = {"jobs": [job_to_dict(job) for job in jobs], "imported": 0, "duplicates": 0, "prepared": 0, "failures": []}
    result.update({"source": source, "query": query, "location": location, "found": len(jobs)})
    return result


def _one_click_hunt(config: AppConfig, payload: dict) -> dict:
    query = str(payload.get("query") or "data scientist")
    location = str(payload.get("location") or "Paris")
    language = str(payload.get("language") or "both")
    limit_queries = _safe_int(payload.get("limit_queries"), 8, maximum=30)
    limit_per_query = _safe_int(payload.get("limit_per_query"), 5, maximum=30)
    prepare_packets = bool(payload.get("prepare_packets", False))
    force_packets = bool(payload.get("force_packets", False))
    internships_only = bool(payload.get("internships_only", False))
    include_multi_source = bool(payload.get("include_multi_source", True))
    # Floor relevance at 20 so a multi-token query (e.g. "stage data") can't admit
    # jobs that match only one weak token. Callers can raise it, never lower it.
    min_relevance = _safe_int(payload.get("min_relevance"), 20, minimum=20, maximum=100)
    france_eu_only = bool(payload.get("france_eu_only", False))
    radius_km = _safe_int(payload.get("radius_km"), 0, minimum=0, maximum=100)
    links = _search_links({"query": query, "location": location, "language": language, "limit": limit_queries, "boards": "recommended"})
    try:
        profile, master_cv, _ = load_profile_bundle(config)
        query_plan = suggest_search_queries(
            profile,
            master_cv,
            seed_query=query,
            location=location,
            language=language,
            internships_only=internships_only,
            limit=limit_queries,
        )
    except Exception:
        query_plan = {
            "queries": [group["query"] for group in links["groups"]],
            "rationale": "Profile loading failed; deterministic query expansion used.",
            "used_ai": False,
            "model": "",
        }
    api_queries = [str(item).strip() for item in query_plan.get("queries", []) if str(item).strip()] or [group["query"] for group in links["groups"]]
    if not is_france_travail_configured():
        return {
            "api_configured": False,
            "message": "France Travail API credentials are not configured, so I prepared curated manual links instead.",
            "manual": links,
            "query_plan": query_plan,
            "imported": 0,
            "duplicates": 0,
            "prepared": 0,
            "jobs": [],
            "failures": [],
            "multi_source": None,
        }

    imported = duplicates = prepared = 0
    jobs_out: list[dict] = []
    failures: list[str] = []
    france_found = 0
    for api_query in api_queries[:limit_queries]:
        try:
            jobs = search_free_api_jobs(
                "francetravail",
                query=api_query,
                location=location,
                limit=limit_per_query,
                internships_only=internships_only,
                min_relevance=min_relevance,
                france_eu_only=france_eu_only,
                radius_km=radius_km,
                use_cache=True,
                cache_ttl_hours=6.0,
            )
        except Exception as exc:
            failures.append(f"{api_query}: {exc}")
            continue
        france_found += len(jobs)
        saved = _save_jobs(config, jobs, prepare_packets=prepare_packets, force_packets=force_packets)
        imported += saved["imported"]
        duplicates += saved["duplicates"]
        prepared += saved["prepared"]
        failures.extend(saved["failures"])
        jobs_out.extend(saved["jobs"])

    multi_summary: dict[str, Any] | None = None
    if include_multi_source:
        per_source: dict[str, int] = {}
        errors: dict[str, str] = {}
        multi_found = multi_imported = multi_duplicates = multi_prepared = 0
        for api_query in api_queries[: min(3, len(api_queries))]:
            try:
                aggregate = search_all_free_sources(
                    query=api_query,
                    location=location,
                    limit_per_source=max(1, min(limit_per_query, 5)),
                    sources=list(KEYWORD_ONLY_SOURCES),
                    internships_only=internships_only,
                    min_relevance=min_relevance,
                    france_eu_only=france_eu_only,
                    radius_km=radius_km,
                    use_cache=True,
                    cache_ttl_hours=6.0,
                )
            except Exception as exc:
                errors[f"multi/{api_query}"] = str(exc)
                continue
            multi_found += len(aggregate["jobs"])
            for source, count in (aggregate.get("per_source") or {}).items():
                per_source[source] = per_source.get(source, 0) + int(count or 0)
            for source, err in (aggregate.get("errors") or {}).items():
                errors[source] = str(err)
            saved = _save_jobs(config, aggregate["jobs"], prepare_packets=prepare_packets, force_packets=force_packets)
            multi_imported += saved["imported"]
            multi_duplicates += saved["duplicates"]
            multi_prepared += saved["prepared"]
            imported += saved["imported"]
            duplicates += saved["duplicates"]
            prepared += saved["prepared"]
            failures.extend(saved["failures"])
            jobs_out.extend(saved["jobs"])
        multi_summary = {
            "found": multi_found,
            "imported": multi_imported,
            "duplicates": multi_duplicates,
            "prepared": multi_prepared,
            "per_source": per_source,
            "errors": errors,
        }
    return {
        "api_configured": True,
        "message": "Smart 1-click hunt finished.",
        "manual": links,
        "query_plan": query_plan,
        "imported": imported,
        "duplicates": duplicates,
        "prepared": prepared,
        "found": france_found + (multi_summary or {}).get("found", 0),
        "jobs": jobs_out,
        "failures": failures,
        "multi_source": multi_summary,
    }


def _export_internships(config: AppConfig, payload: dict) -> dict:
    workbook = payload.get("workbook")
    sheet = str(payload.get("sheet") or "") or None
    workbook_path, count = export_applied_internships(config, workbook_path=workbook, sheet_name=sheet)
    return {"workbook": str(workbook_path), "count": count}
