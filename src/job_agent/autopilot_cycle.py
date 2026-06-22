"""One autopilot cycle: source search, CAC40 sweep, packet build, summary.

Search/DB/pipeline collaborators are reached through the
:mod:`job_agent.autopilot` module object (``ap.<name>``) so the autopilot
tests' ``monkeypatch.setattr(ap, ...)`` seams keep working after the split.
"""
from __future__ import annotations

from typing import Any

import job_agent.autopilot as ap
from job_agent.autopilot_packets import build_packets, maybe_auto_apply


def run_cycle(pilot: Any) -> dict[str, Any]:
    """Run a single hunting cycle and return its summary dict."""
    db = ap.Database(pilot.config.db_path)
    db.initialize()
    ap.ApplicationTracker(db)  # noqa: F841  (constructed for its DB side effect; tests patch this seam)
    added: list[str] = []
    packets: list[str] = []
    errors: list[str] = []
    per_query: dict[str, int] = {}

    ft_ready = pilot.opts.use_france_travail and pilot._france_travail_ready()
    search_queries = pilot._planned_queries()
    _search_sources(pilot, db, search_queries, ft_ready, added, errors, per_query)
    if pilot.opts.use_cac40_sweep:
        _cac40_sweep(pilot, db, added, errors, per_query)

    packets_built, ai_skipped, notifications = build_packets(pilot, db, added, packets, errors)

    pilot.state.jobs_added_total += len(added)
    pilot.state.packets_built_total += packets_built

    maybe_auto_apply(pilot, packets, errors)

    display_errors = [e for e in errors if not ap._is_expected_noise(e)]
    return {
        "jobs_added": len(added),
        "packets_built": packets_built,
        "ai_skipped": ai_skipped,
        "notifications": notifications[:5],
        "errors": display_errors[:10],
        "per_query": per_query,
        "queries": search_queries,
        "france_travail_used": ft_ready,
        "multi_source_used": pilot.opts.use_multi_source,
        "broken_sources": db.list_broken_sources()[:20],
        "ran_at": ap._now_iso(),
    }


def _search_sources(
    pilot: Any,
    db: Any,
    search_queries: list[str],
    ft_ready: bool,
    added: list[str],
    errors: list[str],
    per_query: dict[str, int],
) -> None:
    """Pull France Travail + free multi-source listings for each query."""
    for query in search_queries:
        if pilot._stop_event.is_set():
            break
        cycle_added = 0
        if ft_ready:
            try:
                france_jobs = ap.search_free_api_jobs(
                    "francetravail",
                    query=query,
                    location=pilot.opts.location,
                    limit=pilot.opts.france_travail_limit,
                    contract_type=pilot.opts.contract_type,
                    min_relevance=pilot.opts.min_relevance,
                    france_eu_only=pilot.opts.france_eu_only,
                    radius_km=pilot.opts.radius_km,
                    use_cache=True,
                    cache_ttl_hours=2.0,
                )
                for job in france_jobs:
                    tracked, created = ap.add_job_to_tracker(pilot.config, job)
                    if created:
                        added.append(tracked.id)
                        cycle_added += 1
            except ap.FreeApiError as exc:
                errors.append(f"francetravail/{query}: {exc}")
            except Exception as exc:
                errors.append(f"francetravail/{query}: {type(exc).__name__}: {exc}")

        if pilot.opts.use_multi_source:
            try:
                multi = ap.search_all_free_sources(
                    query=query,
                    location=pilot.opts.location,
                    limit_per_source=pilot.opts.multi_source_limit,
                    sources=list(ap.KEYWORD_ONLY_SOURCES),
                    contract_type=pilot.opts.contract_type,
                    min_relevance=pilot.opts.min_relevance,
                    france_eu_only=pilot.opts.france_eu_only,
                    radius_km=pilot.opts.radius_km,
                    use_cache=True,
                    cache_ttl_hours=2.0,
                )
                for job in multi.get("jobs", []):
                    tracked, created = ap.add_job_to_tracker(pilot.config, job)
                    if created:
                        added.append(tracked.id)
                        cycle_added += 1
                for source, err in (multi.get("errors") or {}).items():
                    errors.append(f"{source}/{query}: {err[:120]}")
            except Exception as exc:
                errors.append(f"multi/{query}: {type(exc).__name__}: {exc}")
        per_query[query] = cycle_added


def _cac40_sweep(
    pilot: Any,
    db: Any,
    added: list[str],
    errors: list[str],
    per_query: dict[str, int],
) -> None:
    """Sweep large-FR employer ATS boards. Dead boards self-disable for 24 h."""
    import requests as _requests
    cac40_added = 0
    cac40_skipped_broken = 0
    for source_kind, slug, display_name in ap.CAC40_ATS_SLUGS:
        if pilot._stop_event.is_set():
            break
        if db.is_source_broken(source_kind, slug):
            cac40_skipped_broken += 1
            continue
        try:
            sweep_jobs = ap.search_free_api_jobs(
                source_kind,
                query=pilot.opts.queries[0] if pilot.opts.queries else "data",
                board=slug,
                limit=pilot.opts.cac40_limit_per_company,
                contract_type=pilot.opts.contract_type,
                min_relevance=pilot.opts.min_relevance,
                france_eu_only=pilot.opts.france_eu_only,
                use_cache=True,
                cache_ttl_hours=4.0,
            )
        except _requests.HTTPError as http_exc:
            status = getattr(http_exc.response, "status_code", None)
            if status in (404, 410, 403):
                # Dead board — mark for 24 h and stay silent.
                db.mark_source_broken(source_kind, slug, status_code=status, reason=str(http_exc)[:200])
                continue
            errors.append(f"{source_kind}/{display_name}: HTTP {status}")
            continue
        except ap.FreeApiError as exc:
            errors.append(f"{source_kind}/{display_name}: {exc}")
            continue
        except Exception as exc:
            errors.append(f"{source_kind}/{display_name}: {type(exc).__name__}: {exc}")
            continue
        for job in sweep_jobs:
            tracked, created = ap.add_job_to_tracker(pilot.config, job)
            if created:
                added.append(tracked.id)
                cac40_added += 1
    per_query["__cac40_sweep__"] = cac40_added
    if cac40_skipped_broken:
        per_query["__cac40_skipped_broken__"] = cac40_skipped_broken
