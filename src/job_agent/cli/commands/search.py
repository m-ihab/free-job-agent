"""Search and discovery command handlers (APIs, multi-source, RSS, links)."""
from __future__ import annotations

import argparse

from job_agent.ai_agent import suggest_search_queries
from job_agent.fingerprint import set_fingerprint
from job_agent.intake.discover import discover_job_links
from job_agent.intake.eu_sources import load_eu_source_registry
from job_agent.intake.free_apis import (
    FreeApiError,
    KEYWORD_ONLY_SOURCES,
    search_all_free_sources,
    supported_source_names,
)
from job_agent.intake.rss import ingest_rss
from job_agent.normalizer import normalize
from job_agent.pipeline import add_job_to_tracker, generate_packet_for_job
from job_agent.validators import load_profile_bundle

from job_agent.cli.commands._common import (
    Panel,
    Table,
    _fail,
    _get_tracker,
    _load_config,
    _load_profiles,
    _print_full_job_links,
    console,
)


def _search_free_api_jobs(*args, **kwargs):
    """Resolve ``search_free_api_jobs`` from :mod:`job_agent.cli.main`.

    Tests monkeypatch ``job_agent.cli.main.search_free_api_jobs``; resolving it
    from that module at call time keeps the patch effective after the move.
    """
    from job_agent.cli import main

    return main.search_free_api_jobs(*args, **kwargs)


def _handle_add_rss(args: argparse.Namespace) -> None:
    config = _load_config()
    tracker = _get_tracker(config)
    jobs = ingest_rss(args.feed_url, limit=args.limit)
    added = 0
    for job in jobs:
        job = set_fingerprint(normalize(job))
        if tracker.db.get_job_by_fingerprint(job.fingerprint):
            continue
        tracker.add_job(job)
        added += 1
    console.print(f"Imported {added}/{len(jobs)} new jobs from RSS feed.")


def _handle_discover_links(args: argparse.Namespace) -> None:
    try:
        links = discover_job_links(args.url, limit=args.limit)
    except Exception as exc:
        _fail(f"Failed to discover links: {exc}")
    if not links:
        console.print("No likely job links found.")
        return
    for link in links:
        console.print(link)


def _handle_search_api(args: argparse.Namespace) -> None:
    config = _load_config()
    config.ensure_dirs()
    try:
        jobs = _search_free_api_jobs(
            args.source,
            query=args.query,
            location=args.location,
            country=args.country,
            board=args.board,
            limit=args.limit,
            page=args.page,
            remote_only=args.remote_only,
            internships_only=args.internships_only,
            min_relevance=args.min_relevance,
            france_eu_only=args.france_eu_only,
            radius_km=args.radius_km,
            use_cache=args.cache,
            cache_ttl_hours=args.cache_ttl_hours,
        )
    except FreeApiError as exc:
        _fail(f"API search error: {exc}")
    except Exception as exc:
        _fail(f"Failed to search source: {exc}")

    if not jobs:
        console.print("No jobs found.")
        return

    table = Table(title=f"{args.source} results", show_header=True, header_style="bold cyan")
    for col in ["#", "Title", "Company", "Location", "Remote", "Source"]:
        table.add_column(col)
    for idx, job in enumerate(jobs, start=1):
        table.add_row(
            str(idx),
            job.title[:60],
            job.company[:30],
            (job.location or "-")[:30],
            "yes" if job.remote else "no",
            job.apply_url or job.source_url or "-",
        )
    console.print(table)
    _print_full_job_links(jobs)

    if args.save:
        added = 0
        duplicates = 0
        for job in jobs:
            _, created = add_job_to_tracker(config, job)
            if created:
                added += 1
            else:
                duplicates += 1
        console.print(f"Saved {added} new jobs ({duplicates} duplicates skipped).")


def _handle_hunt(args: argparse.Namespace) -> None:
    config = _load_config()
    config.ensure_dirs()
    profile, _, _ = _load_profiles(config)
    if not profile:
        _fail("Cannot hunt without valid profile files. Run job-agent copy-examples and validate-profile first.")
    try:
        jobs = _search_free_api_jobs(
            args.source,
            query=args.query,
            location=args.location,
            country=args.country,
            board=args.board,
            limit=args.limit,
            page=args.page,
            remote_only=args.remote_only,
            internships_only=args.internships_only,
            min_relevance=args.min_relevance,
            france_eu_only=args.france_eu_only,
            radius_km=args.radius_km,
            use_cache=args.cache,
            cache_ttl_hours=args.cache_ttl_hours,
        )
    except FreeApiError as exc:
        _fail(f"API search error: {exc}")
    except Exception as exc:
        _fail(f"Failed to search source: {exc}")

    if not jobs:
        console.print("No jobs found.")
        return

    prepared = 0
    skipped = 0
    failed: list[str] = []
    for job in jobs:
        tracked_job, created = add_job_to_tracker(config, job)
        if not created:
            skipped += 1
            continue
        try:
            generate_packet_for_job(config, tracked_job.id, force=args.force)
            prepared += 1
        except Exception as exc:
            failed.append(f"{tracked_job.title} @ {tracked_job.company}: {exc}")
    console.print(
        Panel(
            f"Imported and prepared packets: {prepared}\nDuplicates skipped: {skipped}\nFailures: {len(failed)}\n\n"
            "Open a packet with: job-agent apply-assist <packet-id>\n"
            "Final application submission is still manual.",
            title="Hunt complete",
        )
    )
    for item in failed[:10]:
        console.print(f"Skipped: {item}")


def _handle_api_sources(args: argparse.Namespace) -> None:
    console.print("Supported sources: " + ", ".join(supported_source_names()))
    console.print("Keyword-only sources (no board/credentials): " + ", ".join(KEYWORD_ONLY_SOURCES))
    console.print("France priority source: francetravail (free credentials required).")
    console.print("Discovery sources are read-only; application mode is controlled separately by the Full Auto toggle.")
    registry = load_eu_source_registry()
    console.print(f"Curated EU source registry ({len(registry['sources'])} entries):")
    console.print(registry["attribution"])
    for source in registry["sources"]:
        countries = ",".join(source["countries"])
        auth = "yes" if source["requires_auth"] else "no"
        verified = "yes" if source["verified"] else "no"
        console.print(
            f"{source['id']}: {source['name']} "
            f"access={source['access_type']} countries={countries} auth={auth} verified={verified} "
            f"{source['url']}"
        )


def _handle_smart_plan(args: argparse.Namespace) -> None:
    config = _load_config()
    profile, master_cv, _ = load_profile_bundle(config)
    plan = suggest_search_queries(
        profile,
        master_cv,
        seed_query=args.query,
        location=args.location,
        language=args.language,
        internships_only=args.internships_only,
        limit=args.limit,
    )
    console.print(Panel(
        f"Mode: {'local AI' if plan.get('used_ai') else 'deterministic'}\n"
        f"Model: {plan.get('model') or '-'}\n"
        f"Rationale: {plan.get('rationale') or '-'}",
        title="Smart search plan",
    ))
    for idx, query in enumerate(plan.get("queries", []), start=1):
        print(f"{idx}. {query}")


def _handle_multi_search(args: argparse.Namespace) -> None:
    config = _load_config()
    config.ensure_dirs()
    sources = [s.strip() for s in (args.sources or "").split(",") if s.strip()] or None
    result = search_all_free_sources(
        query=args.query,
        location=args.location,
        country=args.country,
        limit_per_source=args.limit,
        sources=sources,
        remote_only=args.remote_only,
        internships_only=args.internships_only,
        min_relevance=args.min_relevance,
        france_eu_only=args.france_eu_only,
        radius_km=args.radius_km,
        use_cache=args.cache,
    )
    table = Table(title=f"Multi-source results for '{args.query}'", show_header=True, header_style="bold cyan")
    for col in ["#", "Source", "Title", "Company", "Location"]:
        table.add_column(col)
    for idx, job in enumerate(result["jobs"], start=1):
        table.add_row(str(idx), job.source.replace("api:", ""), job.title[:60], job.company[:30], (job.location or "-")[:30])
    console.print(table)
    _print_full_job_links(result["jobs"])
    summary_lines = [f"{src}: {count}" for src, count in result["per_source"].items()]
    if result["errors"]:
        summary_lines.append("Errors: " + "; ".join(f"{k}={v[:80]}" for k, v in result["errors"].items()))
    console.print(Panel("\n".join(summary_lines) or "No sources returned data.", title="Per-source counts"))
    if args.save and result["jobs"]:
        added = duplicates = 0
        for job in result["jobs"]:
            _, created = add_job_to_tracker(config, job)
            if created:
                added += 1
            else:
                duplicates += 1
        console.print(f"Saved {added} new jobs ({duplicates} duplicates skipped).")
