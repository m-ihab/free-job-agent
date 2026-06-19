"""France/Paris workflow command handlers."""
from __future__ import annotations

import argparse
import json
import sys

from job_agent.intake.free_apis import FreeApiError
from job_agent.intake.france_market import (
    DEFAULT_FRANCE_DATA_AI_QUERIES,
    board_notes,
    build_france_search_urls,
    cac40_targets,
    expand_france_search_queries,
)
from job_agent.pipeline import add_job_to_tracker, generate_packet_for_job

from job_agent.cli.commands._common import (
    Panel,
    Table,
    _fail,
    _load_config,
    _load_profiles,
    console,
)


def _search_free_api_jobs(*args, **kwargs):
    """Resolve ``search_free_api_jobs`` from :mod:`job_agent.cli.main`."""
    from job_agent.cli import main

    return main.search_free_api_jobs(*args, **kwargs)


def _handle_france_setup(args: argparse.Namespace) -> None:
    setup_text = (
        "Important: your normal candidate login is not an API client id/secret.\n"
        "1. Request free France Travail API access for 'API Offres d'emploi'.\n"
        "2. Set these environment variables after approval:\n"
        "   FRANCE_TRAVAIL_CLIENT_ID=...\n"
        "   FRANCE_TRAVAIL_CLIENT_SECRET=...\n"
        "   FRANCE_TRAVAIL_SCOPE='api_offresdemploiv2 o2dsoffre'\n"
        "3. Run: job-agent search-api francetravail --query 'data scientist stage' --location Paris --save --internships-only\n"
        "4. Export your submitted internship tracker with: job-agent export internships\n"
        "5. For Welcome to the Jungle, LinkedIn, Indeed, Glassdoor, HelloWork, Apec, Stage.fr: use france-search-urls, then add promising URLs with job-agent add url.\n"
        "6. For a guided profile setup, run: job-agent setup-wizard\n\n"
        "This tool does not scrape logged-in boards and does not auto-submit applications."
    )
    console.print(Panel(setup_text, title="France/Paris setup"))


def _handle_france_search_urls(args: argparse.Namespace) -> None:
    queries = [args.query] if args.single_query else expand_france_search_queries(args.query, limit=args.limit, language=args.language)
    notes = board_notes()
    recommended_only = args.boards == "recommended"
    board_rows = build_france_search_urls(args.query, args.location, recommended_only=recommended_only)
    if args.format != "json":
        console.print("Boards: " + ", ".join(row[1] for row in board_rows))
        console.print(f"Language: {args.language}")
        if not args.single_query:
            console.print("Expanded queries: " + "; ".join(queries))

    rows: list[dict[str, str]] = []
    for query in queries:
        for key, name, url in build_france_search_urls(query, args.location, recommended_only=recommended_only):
            rows.append(
                {
                    "query": query,
                    "board_key": key,
                    "board": name,
                    "url": url,
                    "note": notes.get(key, ""),
                }
            )

    if args.format == "json":
        output = json.dumps(rows, ensure_ascii=False, indent=2)
        sys.stdout.write(output + "\n")
    elif args.format == "table":
        table = Table(title=f"France search URLs: {args.query} / {args.location}", show_header=True, header_style="bold cyan")
        for col in ["Query", "Board", "URL", "Note"]:
            table.add_column(col)
        for row in rows:
            table.add_row(row["query"], row["board"], row["url"], row["note"])
        console.print(table)
        output = "\n".join(f"{row['query']} | {row['board']} | {row['url']} | {row['note']}" for row in rows)
    else:
        lines: list[str] = []
        for idx, row in enumerate(rows, start=1):
            lines.append(f"[{idx}] {row['query']} | {row['board']}")
            lines.append(row["url"])
            if row["note"]:
                lines.append(f"    Note: {row['note']}")
            lines.append("")
        output = "\n".join(lines).rstrip()
        sys.stdout.write(output + "\n")

    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
        console.print(f"Saved full URLs to: {args.output}")


def _handle_france_targets(args: argparse.Namespace) -> None:
    table = Table(title="France CAC 40 / large-company targets", show_header=True, header_style="bold cyan")
    for col in ["Company", "Sector", "Careers URL", "Search hint"]:
        table.add_column(col)
    for target in cac40_targets(limit=args.limit):
        table.add_row(target.name, target.sector, target.careers_url, target.search_hint)
    console.print(table)


def _handle_france_hunt(args: argparse.Namespace) -> None:
    config = _load_config()
    config.ensure_dirs()
    profile, _, _ = _load_profiles(config)
    if not profile and args.packets:
        _fail("Cannot generate packets without valid profile files. Run copy-examples, edit them, then validate-profile.")
    queries = expand_france_search_queries(args.query, limit=args.limit_queries, language=args.language) if args.query.strip() else DEFAULT_FRANCE_DATA_AI_QUERIES[: args.limit_queries]
    imported = duplicates = prepared = 0
    failures: list[str] = []
    for query in queries:
        try:
            jobs = _search_free_api_jobs(
                "francetravail",
                query=query,
                location=args.location,
                limit=args.limit,
                internships_only=args.internships_only,
                min_relevance=args.min_relevance,
                france_eu_only=args.france_eu_only,
                radius_km=args.radius_km,
                use_cache=args.cache,
                cache_ttl_hours=6.0,
            )
        except FreeApiError as exc:
            console.print(f"France Travail not available for query '{query}': {exc}")
            console.print("Run job-agent france-setup, or use job-agent france-search-urls for manual sources.")
            continue
        except Exception as exc:
            failures.append(f"{query}: {exc}")
            continue
        for job in jobs:
            tracked_job, created = add_job_to_tracker(config, job)
            if not created:
                duplicates += 1
                continue
            imported += 1
            if args.packets:
                try:
                    generate_packet_for_job(config, tracked_job.id, force=args.force)
                    prepared += 1
                except Exception as exc:
                    failures.append(f"{tracked_job.title} @ {tracked_job.company}: {exc}")
    console.print(
        Panel(
            f"Imported: {imported}\nDuplicates: {duplicates}\nPackets prepared: {prepared}\nFailures: {len(failures)}\n\n"
            "Manual fallback: job-agent france-search-urls --query 'data science stage' --location Paris",
            title="France hunt complete",
        )
    )
    for item in failures[:10]:
        console.print(f"Skipped: {item}")
