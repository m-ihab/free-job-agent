"""Local-first CLI for free-job-agent.

This module intentionally uses the Python standard library for argument
parsing so the core workflow still works in environments where Click is not
available. Tests continue to use a tiny local ``click.testing`` shim.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import webbrowser
from pathlib import Path

try:  # pragma: no cover - optional pretty output
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except Exception:  # pragma: no cover
    class Console:
        def print(self, *args, **kwargs):
            print(*[str(a) for a in args])

    class Table:
        def __init__(self, title: str | None = None, *cols, **kwargs):
            self.title = title
            self.cols = list(cols)
            self.rows: list[tuple[str, ...]] = []

        def add_column(self, name, *args, **kwargs):
            self.cols.append(name)

        def add_row(self, *values):
            self.rows.append(tuple(str(v) for v in values))

        def __str__(self):
            lines = [self.title or ""] if self.title else []
            if self.cols:
                lines.append(" | ".join(map(str, self.cols)))
            lines.extend(" | ".join(row) for row in self.rows)
            return "\n".join(lines)

    class Panel:
        def __init__(self, text, title: str | None = None):
            self.text = text
            self.title = title

        def __str__(self):
            return f"{self.title or ''}\n{self.text}"

from job_agent.config import AppConfig
from job_agent.ai_agent import suggest_search_queries
from job_agent.db.database import Database
from job_agent.enrichment import EnrichOptions, enrich_job
from job_agent.exporters.internship_workbook import export_applied_internships
from job_agent.fingerprint import set_fingerprint
from job_agent.intake.discover import discover_job_links
from job_agent.intake.file import ingest_file
from job_agent.intake.free_apis import (
    FreeApiError,
    KEYWORD_ONLY_SOURCES,
    search_all_free_sources,
    search_free_api_jobs,
    supported_source_names,
)
from job_agent.intake.france_market import (
    DEFAULT_FRANCE_DATA_AI_QUERIES,
    board_notes,
    build_france_search_urls,
    cac40_targets,
    expand_france_search_queries,
)
from job_agent.intake.paste import ingest_paste
from job_agent.intake.rss import ingest_rss
from job_agent.intake.url import ingest_url
from job_agent.normalizer import normalize
from job_agent.pipeline import add_job_to_tracker, generate_packet_for_job, process_file
from job_agent.polish import PolishOptions, ollama_status
from job_agent.profile_enrich import (
    enrich_from_github,
    enrich_from_linkedin_skills,
    linkedin_handle,
)
from job_agent.schemas.job import JobStatus
from job_agent.schemas.packet import PacketStatus
from job_agent.scorer import score_job
from job_agent.tracker import ApplicationTracker
from job_agent.validators import load_profile_bundle, validate_profile_bundle

console = Console()


class CLIError(Exception):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _load_config() -> AppConfig:
    return AppConfig.load()


def _get_tracker(config: AppConfig) -> ApplicationTracker:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    return ApplicationTracker(db)


def _load_profiles(config: AppConfig):
    try:
        return load_profile_bundle(config)
    except Exception as exc:
        console.print(f"Warning: {exc}")
        return None, None, None


def _fail(message: str, code: int = 1) -> None:
    raise CLIError(message, code=code)


def _add_job(job, config: AppConfig) -> None:
    tracker = _get_tracker(config)
    job = normalize(job)
    job = set_fingerprint(job)
    existing = tracker.db.get_job_by_fingerprint(job.fingerprint)
    if existing:
        console.print(f"Duplicate detected. Job already exists: {existing.id}")
        return
    tracker.add_job(job)
    console.print(f"Added job {job.id[:8]} - {job.title} @ {job.company}")


def _find_examples_dir(config: AppConfig) -> Path:
    candidates = [
        config.examples_dir,
        Path.cwd() / "examples",
        Path(__file__).resolve().parents[3] / "examples",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise FileNotFoundError(
        "Could not find examples directory. Run from the repo root or set examples_dir in config.json."
    )


def _handle_init(args) -> None:
    config = AppConfig()
    config.ensure_dirs()
    config.save()
    Database(config.db_path).initialize()  # type: ignore[arg-type]
    console.print(f"Initialized job-agent data directory at: {config.data_dir}")
    console.print(f"Place profile files in: {config.profiles_dir}")


def _handle_copy_examples(args) -> None:
    config = AppConfig.load()
    config.ensure_dirs()
    try:
        src_dir = _find_examples_dir(config)
    except Exception as exc:
        _fail(str(exc))
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        dst = config.profiles_dir / name  # type: ignore[operator]
        src = src_dir / name
        if dst.exists():
            console.print(f"Exists, not overwriting: {dst}")
        else:
            shutil.copyfile(src, dst)
            console.print(f"Copied: {dst}")


def _handle_validate_profile(args) -> None:
    report = validate_profile_bundle(_load_config())
    if report.errors:
        console.print("Profile validation failed")
        for err in report.errors:
            console.print(f"  - {err}")
        _fail("Profile validation failed", code=1)
    console.print("Profile validation passed")
    for warning in report.warnings:
        console.print(f"Warning: {warning}")


def _handle_add_paste(args) -> None:
    console.print("Paste job description below. Press Ctrl+D (Ctrl+Z on Windows) when done:")
    text = sys.stdin.read()
    _add_job(ingest_paste(text, title=args.title or None, company=args.company or None, url=args.url or None), _load_config())


def _handle_add_file(args) -> None:
    _add_job(ingest_file(args.path, title=args.title or None, company=args.company or None, url=args.url or None), _load_config())


def _handle_add_url(args) -> None:
    try:
        job = ingest_url(args.url)
    except Exception as exc:
        _fail(f"Failed to fetch URL: {exc}")
    _add_job(job, _load_config())


def _handle_add_rss(args) -> None:
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


def _handle_discover_links(args) -> None:
    try:
        links = discover_job_links(args.url, limit=args.limit)
    except Exception as exc:
        _fail(f"Failed to discover links: {exc}")
    if not links:
        console.print("No likely job links found.")
        return
    for link in links:
        console.print(link)


def _handle_search_api(args) -> None:
    config = _load_config()
    config.ensure_dirs()
    try:
        jobs = search_free_api_jobs(
            args.source,
            query=args.query,
            location=args.location,
            country=args.country,
            board=args.board,
            limit=args.limit,
            page=args.page,
            remote_only=args.remote_only,
            internships_only=args.internships_only,
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


def _handle_hunt(args) -> None:
    config = _load_config()
    config.ensure_dirs()
    profile, _, _ = _load_profiles(config)
    if not profile:
        _fail("Cannot hunt without valid profile files. Run job-agent copy-examples and validate-profile first.")
    try:
        jobs = search_free_api_jobs(
            args.source,
            query=args.query,
            location=args.location,
            country=args.country,
            board=args.board,
            limit=args.limit,
            page=args.page,
            remote_only=args.remote_only,
            internships_only=args.internships_only,
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


def _handle_api_sources(args) -> None:
    console.print("Supported sources: " + ", ".join(supported_source_names()))
    console.print("Keyword-only sources (no board/credentials): " + ", ".join(KEYWORD_ONLY_SOURCES))
    console.print("France priority source: francetravail (free credentials required).")
    console.print("All sources are read-only here; final submission remains manual.")


def _find_local_tool(name: str) -> str | None:
    appdata = Path.home() / "AppData" / "Roaming"
    local = Path.home() / "AppData" / "Local"
    program_files = Path("C:/Program Files")
    candidates = {
        "perl": [
            Path("C:/Strawberry/perl/bin/perl.exe"),
            Path("C:/Perl64/bin/perl.exe"),
            Path("C:/Perl/bin/perl.exe"),
        ],
        "node": [
            program_files / "nodejs" / "node.exe",
        ],
        "npm": [
            program_files / "nodejs" / "npm.cmd",
            appdata / "npm" / "npm.cmd",
        ],
        "openclaw": [
            appdata / "npm" / "openclaw.cmd",
            appdata / "npm" / "openclaw.ps1",
            local / "Programs" / "openclaw" / "openclaw.exe",
        ],
    }.get(name, [])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which(name)


def _handle_ai_status(args) -> None:
    status = ollama_status(PolishOptions.from_env())
    compiler_tools = {
        "pdflatex": shutil.which("pdflatex"),
        "latexmk": shutil.which("latexmk"),
        "perl": _find_local_tool("perl"),
        "node": _find_local_tool("node"),
        "npm": _find_local_tool("npm"),
        "openclaw": _find_local_tool("openclaw"),
    }
    lines = [
        f"Ollama reachable: {'yes' if status['reachable'] else 'no'}",
        f"Selected model: {status['selected_model'] or '-'}",
        f"Installed models: {', '.join(status['models']) if status['models'] else '-'}",
        f"Ollama polish opt-in: {'enabled' if status['enabled'] else 'disabled'}",
        "",
        "Local tools:",
    ]
    for name, path in compiler_tools.items():
        lines.append(f"- {name}: {path or 'not on PATH'}")
    if not compiler_tools["npm"] or not compiler_tools["openclaw"]:
        lines.append("")
        lines.append("If npm/openclaw are installed but shown as missing, restart PowerShell or add their install folder to PATH.")
    console.print(Panel("\n".join(lines), title="AI / local-tool readiness"))


def _handle_smart_plan(args) -> None:
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


def _handle_multi_search(args) -> None:
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


def _print_full_job_links(jobs) -> None:
    """Print full, copyable result URLs after Rich tables.

    Rich tables are easier to scan, but terminals often truncate long links.
    Keeping a plain-text block here makes the CLI useful for direct copy/paste.
    """
    rows: list[tuple[int, str, str, str]] = []
    for idx, job in enumerate(jobs, start=1):
        url = job.apply_url or job.source_url
        if not url:
            continue
        rows.append((idx, job.title, job.company, url))
    if not rows:
        return

    print()
    print("Full URLs:")
    for idx, title, company, url in rows:
        print(f"{idx}. {title} @ {company}")
        print(f"   {url}")


def _handle_ui(args) -> None:
    from job_agent.ui.server import run_server

    run_server(host=args.host, port=args.port, open_browser=not args.no_open)


def _handle_france_setup(args) -> None:
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


_WIZARD_STEPS = [
    ("school", "School / university", "DSTI School of Engineering"),
    ("program", "Program / degree", "Applied MSc in Data Science & AI"),
    ("availability", "Earliest internship start date", "ASAP, end-of-studies 6-month stage"),
    ("duration", "Preferred internship duration", "6 months"),
    ("alternance_rhythm", "Alternance rhythm if relevant", "3 weeks company / 1 week school"),
    ("french_level", "French level (A1/A2/B1/B2/C1/C2)", "A2 (targeting B1)"),
    ("english_level", "English level (A1/A2/B1/B2/C1/C2/Fluent)", "Fluent"),
    ("work_auth", "Work authorization status in France", "Manual completion required before application submission."),
    ("visa_sponsorship", "Do you need visa sponsorship?", "Manual completion required before application submission."),
    ("convention", "Can your school provide a convention de stage?", "Manual completion required before application submission."),
    ("relocation", "Open to relocation outside Paris?", "No"),
    ("remote_preference", "Remote / hybrid / onsite preference", "Hybrid in Paris; remote within France OK"),
]


def _handle_enrich_github(args) -> None:
    config = _load_config()
    config.ensure_dirs()
    handle = args.handle.strip() if args.handle else ""
    if not handle and config.profiles_dir:
        try:
            profile_json = json.loads((config.profiles_dir / "candidate_profile.json").read_text(encoding="utf-8"))
            github_url = (profile_json.get("contact") or {}).get("github_url") or ""
            handle = github_url.rstrip("/").rsplit("/", 1)[-1] if github_url else ""
        except Exception:
            handle = ""
    if not handle:
        _fail("Provide --handle or set contact.github_url in candidate_profile.json.")
    try:
        report = enrich_from_github(Path(config.profiles_dir), handle, add_projects=not args.no_projects)
    except Exception as exc:
        _fail(f"GitHub enrichment failed: {exc}")
    console.print(Panel(
        f"GitHub handle: {report['handle']}\n"
        f"Public repos: {report['public_repos']}\n"
        f"Top languages: {', '.join(report['languages_seen'][:8])}\n"
        f"Skills added: {', '.join(report['added_skills']) or 'none'}\n"
        f"Projects added: {', '.join(report['added_projects']) or 'none'}\n"
        f"GitHub URL written: {report['updated_contact']}",
        title="GitHub enrichment complete",
    ))


def _handle_enrich_linkedin(args) -> None:
    config = _load_config()
    config.ensure_dirs()
    if args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8")
        except Exception as exc:
            _fail(f"Could not read {args.file}: {exc}")
    else:
        console.print("Paste your LinkedIn Skills section (one per line). Press Ctrl+D (Ctrl+Z on Windows) when done:")
        text = sys.stdin.read()
    try:
        report = enrich_from_linkedin_skills(Path(config.profiles_dir), text)
    except Exception as exc:
        _fail(f"LinkedIn enrichment failed: {exc}")
    console.print(Panel(
        f"Parsed skills: {report['parsed_count']}\n"
        f"Newly added: {', '.join(report['added_skills']) or 'none'}\n"
        f"Updated: {report['candidate_path']}, {report['master_cv_path']}",
        title="LinkedIn enrichment complete",
    ))


def _handle_setup_wizard(args) -> None:
    config = _load_config()
    config.ensure_dirs()
    interactive = sys.stdin.isatty() and not args.non_interactive
    console.print(Panel(
        "Stage/alternance profile wizard — press Enter to accept the suggested value, or type a custom one. "
        "Sensitive answers stay locked behind manual review.",
        title="Setup wizard",
    ))
    answers: dict[str, str] = {}
    for key, label, default in _WIZARD_STEPS:
        if interactive:
            console.print(f"{label} [{default}]:")
            line = sys.stdin.readline().strip()
            answers[key] = line or default
        else:
            answers[key] = default

    qa_path = config.profiles_dir / "master_qa_profile.json"  # type: ignore[operator]
    try:
        existing = json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.exists() else {"entries": [], "hold_if_missing": True}
    except Exception:
        existing = {"entries": [], "hold_if_missing": True}

    def _replace_or_append(entry_id: str, patterns: list[str], answer: str, category: str, jurisdiction: str | None = None, sensitive: bool = False) -> None:
        for item in existing.get("entries", []):
            if item.get("id") == entry_id:
                item["question_patterns"] = patterns
                item["answer"] = answer
                item["category"] = category
                item["locked"] = True
                item["sensitive"] = sensitive
                if jurisdiction:
                    item["jurisdiction"] = jurisdiction
                return
        existing.setdefault("entries", []).append({
            "id": entry_id,
            "question_patterns": patterns,
            "answer": answer,
            "category": category,
            "jurisdiction": jurisdiction or "FR",
            "locked": True,
            "sensitive": sensitive,
        })

    _replace_or_append("work_authorization_france", [
        "are you authorized to work in france",
        "êtes-vous autorisé à travailler en france",
        "autorisation de travail",
        "droit de travailler en france",
    ], answers["work_auth"], "work_authorization", sensitive=True)
    _replace_or_append("visa_sponsorship_france", [
        "do you require visa sponsorship",
        "will you require sponsorship",
        "avez-vous besoin d'un visa",
        "sponsorship visa",
    ], answers["visa_sponsorship"], "work_authorization", sensitive=True)
    _replace_or_append("internship_agreement_france", [
        "convention de stage",
        "can you provide an internship agreement",
        "avez-vous une convention de stage",
    ], answers["convention"], "internship_agreement", sensitive=True)
    _replace_or_append("availability_france", [
        "availability",
        "date de disponibilité",
        "start date",
        "quand pouvez-vous commencer",
    ], answers["availability"], "availability")
    _replace_or_append("internship_duration", [
        "internship duration",
        "durée du stage",
        "duration",
    ], answers["duration"], "availability")
    _replace_or_append("alternance_rhythm", [
        "alternance rhythm",
        "rythme alternance",
        "rythme de l'alternance",
    ], answers["alternance_rhythm"], "availability")
    _replace_or_append("languages_fr_en", [
        "languages",
        "langues",
        "french level",
        "english level",
        "niveau de français",
        "niveau d'anglais",
    ], f"French: {answers['french_level']}. English: {answers['english_level']}. Arabic: Native.", "languages")
    _replace_or_append("school_program", [
        "school",
        "university",
        "école",
        "université",
    ], f"{answers['program']} at {answers['school']}", "education")
    _replace_or_append("relocation_preference", [
        "relocation",
        "are you willing to relocate",
        "déménagement",
    ], answers["relocation"], "preferences")
    _replace_or_append("remote_preference", [
        "remote",
        "hybrid",
        "télétravail",
        "work preference",
    ], answers["remote_preference"], "preferences")

    existing.setdefault("hold_if_missing", True)
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    console.print(Panel(
        f"Wrote {qa_path}\n"
        f"Captured: {len(answers)} answers. Sensitive answers (visa, work auth, convention) remain locked for manual review.",
        title="Setup wizard complete",
    ))


def _handle_export_internships(args) -> None:
    config = _load_config()
    try:
        workbook_path, count = export_applied_internships(config, workbook_path=args.workbook, sheet_name=args.sheet)
    except Exception as exc:
        _fail(f"Failed to export internship workbook: {exc}")
    console.print(
        Panel(
            f"Exported {count} applied internship(s)\nWorkbook: {workbook_path}",
            title="Internship export complete",
        )
    )


def _build_enrich_options(args) -> EnrichOptions:
    flags = [
        args.rome,
        args.anotea,
        args.training,
        args.labour_market,
        args.territory,
        args.employer,
        args.other,
    ]
    if not any(flags):
        return EnrichOptions()
    return EnrichOptions(
        rome=args.rome,
        anotea=args.anotea,
        training=args.training,
        labour_market=args.labour_market,
        territory=args.territory,
        employer=args.employer,
        other=args.other,
    )


def _handle_enrich(args) -> None:
    config = _load_config()
    config.ensure_dirs()
    options = _build_enrich_options(args)
    tracker = _get_tracker(config)

    job_ids: list[str] = []
    if args.job_id:
        job_ids = [args.job_id]
    elif args.status:
        try:
            status = JobStatus(args.status.upper())
        except ValueError:
            _fail(f"Unknown status: {args.status}")
        job_ids = [job.id for job in tracker.list_jobs(status=status, limit=args.limit)]
    else:
        _fail("Provide a job id or --status to enrich multiple jobs.")

    if not job_ids:
        console.print("No jobs found for enrichment.")
        return

    for job_id in job_ids:
        report = enrich_job(config, job_id, options)
        sources = report.get("sources", {})
        ok = sum(1 for value in sources.values() if str(value).startswith("ok"))
        console.print(
            Panel(
                f"Job: {job_id}\nEndpoints ok: {ok}/{len(sources)}",
                title="Enrichment complete",
            )
        )


def _handle_france_search_urls(args) -> None:
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


def _handle_france_targets(args) -> None:
    table = Table(title="France CAC 40 / large-company targets", show_header=True, header_style="bold cyan")
    for col in ["Company", "Sector", "Careers URL", "Search hint"]:
        table.add_column(col)
    for target in cac40_targets(limit=args.limit):
        table.add_row(target.name, target.sector, target.careers_url, target.search_hint)
    console.print(table)


def _handle_france_hunt(args) -> None:
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
            jobs = search_free_api_jobs(
                "francetravail",
                query=query,
                location=args.location,
                limit=args.limit,
                internships_only=args.internships_only,
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


def _handle_list(args) -> None:
    config = _load_config()
    tracker = _get_tracker(config)
    status = None
    if args.status:
        try:
            status = JobStatus(args.status.upper())
        except ValueError:
            _fail(f"Unknown status: {args.status}")
    jobs = tracker.list_jobs(status=status)
    if not jobs:
        console.print("No jobs found.")
        return
    table = Table(title="Jobs", show_header=True, header_style="bold cyan")
    for col in ["ID", "Title", "Company", "Status", "Score", "Decision", "Date"]:
        table.add_column(col)
    for job in jobs:
        table.add_row(
            job.id[:8],
            job.title,
            job.company,
            job.status.value,
            str(job.fit_score if job.fit_score is not None else "-"),
            job.fit_decision or "-",
            job.created_at[:10],
        )
    console.print(table)


def _handle_show(args) -> None:
    tracker = _get_tracker(_load_config())
    job = tracker.get_job(args.job_id)
    if not job:
        _fail(f"Job not found: {args.job_id}")
    console.print(
        Panel(
            f"{job.title} @ {job.company}\n"
            f"Status: {job.status.value} | Score: {job.fit_score if job.fit_score is not None else '-'} | Decision: {job.fit_decision or '-'}\n"
            f"Location: {job.location or '-'} | Remote: {job.remote} | Work mode: {job.work_mode or '-'}\n"
            f"Source: {job.source} | Created: {job.created_at[:10]}\n\n"
            f"Description:\n{job.description[:700]}{'...' if len(job.description) > 700 else ''}\n\n"
            f"Tech Stack: {', '.join(job.tech_stack) or '-'}\n"
            f"Apply URL: {job.apply_url or '-'}",
            title=f"Job {job.id[:8]}",
        )
    )


def _handle_score(args) -> None:
    config = _load_config()
    tracker = _get_tracker(config)
    profile, _, _ = _load_profiles(config)
    if not profile:
        _fail("Cannot score without candidate_profile.json.")
    job = tracker.get_job(args.job_id)
    if not job:
        _fail(f"Job not found: {args.job_id}")
    breakdown = score_job(job, profile)
    job.fit_score = breakdown.total_score
    job.fit_confidence = breakdown.confidence
    job.fit_decision = breakdown.decision
    job.fit_notes = breakdown.notes
    job.missing_requirements = breakdown.missing_requirements
    job.risk_flags = sorted(set(job.risk_flags + breakdown.risk_flags))
    tracker.db.save_job(job)
    tracker.update_status(job.id, JobStatus.SCORED)
    console.print(
        Panel(
            f"Total Score: {breakdown.total_score}/100\n"
            f"Decision: {breakdown.decision} | Confidence: {breakdown.confidence:.2f}\n"
            f"Skill: {breakdown.skill_score}/100 | Title: {breakdown.title_score}/100 | Location: {breakdown.location_score}/100\n\n"
            + "\n".join(f"  - {note}" for note in breakdown.notes),
            title=f"Score: {job.title[:40]}",
        )
    )


def _handle_apply(args) -> None:
    config = _load_config()
    config.ensure_dirs()
    try:
        packet = generate_packet_for_job(config, args.job_id, force=args.force)
    except Exception as exc:
        _fail(f"Cannot generate packet: {exc}")
    console.print(
        Panel(
            f"Packet generated\n"
            f"Packet ID: {packet.id}\nStatus: {packet.status.value}\n"
            f"CV PDF: {packet.tailored_cv_pdf_path}\nCover Letter: {packet.cover_letter_pdf_path}\n"
            f"Assistant: {next((a.path for a in packet.artifacts if a.kind == 'assistant_html'), '-')}\n\n"
            "Review everything manually before submitting.",
            title="Application Packet",
        )
    )


def _handle_process_file(args) -> None:
    try:
        job, packet, created = process_file(
            _load_config(),
            args.path,
            title=args.title or None,
            company=args.company or None,
            url=args.url or None,
            force=args.force,
        )
    except Exception as exc:
        _fail(f"Processing failed: {exc}")
    if not created:
        console.print(f"Duplicate detected: existing job {job.id[:8]}")
        return
    assert packet is not None
    console.print(f"Processed {job.title} @ {job.company} | score={packet.fit_score}/100 | packet={packet.id}")


def _handle_status(args) -> None:
    tracker = _get_tracker(_load_config())
    try:
        status = JobStatus(args.new_status.upper())
    except ValueError:
        valid = [status.value for status in JobStatus]
        _fail(f"Unknown status: {args.new_status}. Valid: {valid}")
    try:
        tracker.update_status(args.job_id, status, note=args.note)
    except ValueError as exc:
        _fail(str(exc))
    console.print(f"Updated {args.job_id[:8]} -> {status.value}")


def _handle_history(args) -> None:
    tracker = _get_tracker(_load_config())
    events = tracker.get_history(args.job_id)
    if not events:
        console.print("No events found.")
        return
    table = Table(title=f"History: {args.job_id[:8]}", show_header=True)
    for col in ["#", "Type", "Data", "At"]:
        table.add_column(col)
    for event in events:
        table.add_row(str(event["id"]), event["event_type"], str(event["event_data"]), event["created_at"][:19])
    console.print(table)


def _handle_apply_assist(args) -> None:
    tracker = _get_tracker(_load_config())
    packet = tracker.db.resolve_packet(args.packet_id)
    if not packet:
        _fail(f"Packet not found: {args.packet_id}")
    job = tracker.get_job(packet.job_id)
    packet.status = PacketStatus.ASSISTED_APPLY_OPENED
    tracker.db.save_packet(packet)
    if job:
        job.status = JobStatus.ASSISTED_APPLY_OPENED
        tracker.db.save_job(job)
    tracker.db.log_event(job.id if job else None, "ASSISTED_APPLY_OPENED", {"packet_id": packet.id}, packet_id=packet.id)
    assistant = next((artifact for artifact in packet.artifacts if artifact.kind == "assistant_html"), None)
    if assistant:
        console.print(f"Assistant page: {assistant.path}")
        if args.open_browser:
            webbrowser.open(Path(assistant.path).resolve().as_uri())
    if job and job.apply_url:
        console.print(f"Apply URL: {job.apply_url}")
        if args.open_browser:
            webbrowser.open(job.apply_url)


def _handle_mark_submitted(args) -> None:
    tracker = _get_tracker(_load_config())
    packet = tracker.db.resolve_packet(args.packet_id)
    if not packet:
        _fail(f"Packet not found: {args.packet_id}")
    packet.status = PacketStatus.MANUALLY_SUBMITTED
    tracker.db.save_packet(packet)
    job = tracker.get_job(packet.job_id)
    if job:
        job.status = JobStatus.MANUALLY_SUBMITTED
        tracker.db.save_job(job)
    tracker.db.log_event(packet.job_id, "MANUALLY_SUBMITTED", {"packet_id": packet.id, "note": args.note}, packet_id=packet.id)
    console.print(f"Marked manually submitted: {packet.id}")


def _handle_packet_show(args) -> None:
    tracker = _get_tracker(_load_config())
    packet = tracker.db.resolve_packet(args.job_or_packet_id)
    if packet is None:
        job = tracker.get_job(args.job_or_packet_id)
        if job:
            packets = tracker.db.get_packets_for_job(job.id)
            packet = packets[0] if packets else None
    if not packet:
        console.print("No packet found.")
        return
    artifacts = "\n".join(f"  - {artifact.kind}: {artifact.path}" for artifact in packet.artifacts)
    console.print(
        Panel(
            f"Packet ID: {packet.id}\nVersion: {packet.version}\nStatus: {packet.status.value}\nFit: {packet.fit_score}\n"
            f"CV PDF: {packet.tailored_cv_pdf_path or '-'}\nLetter: {packet.cover_letter_pdf_path or '-'}\nArtifacts:\n{artifacts}",
            title="Packet",
        )
    )


class LocalCLIApp:
    prog = "job-agent"

    def build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=self.prog, description="Free, local-first job-search and application assistant.")
        sub = parser.add_subparsers(dest="command")
        sub.required = True

        init_p = sub.add_parser("init", help="Initialize data directory and config.")
        init_p.set_defaults(handler=_handle_init)

        copy_p = sub.add_parser("copy-examples", help="Copy example profile files.")
        copy_p.set_defaults(handler=_handle_copy_examples)

        validate_p = sub.add_parser("validate-profile", help="Validate candidate profile files.")
        validate_p.set_defaults(handler=_handle_validate_profile)

        add_p = sub.add_parser("add", help="Add jobs from various sources.")
        add_sub = add_p.add_subparsers(dest="add_command")
        add_sub.required = True

        add_paste = add_sub.add_parser("paste", help="Add a job from stdin paste mode.")
        add_paste.add_argument("--title", default="")
        add_paste.add_argument("--company", default="")
        add_paste.add_argument("--url", default="")
        add_paste.set_defaults(handler=_handle_add_paste)

        add_file = add_sub.add_parser("file", help="Add a job from a text/markdown file.")
        add_file.add_argument("path", type=Path)
        add_file.add_argument("--title", default="")
        add_file.add_argument("--company", default="")
        add_file.add_argument("--url", default="")
        add_file.set_defaults(handler=_handle_add_file)

        add_url = add_sub.add_parser("url", help="Add a job from a public URL.")
        add_url.add_argument("url")
        add_url.set_defaults(handler=_handle_add_url)

        add_rss = add_sub.add_parser("rss", help="Add jobs from an RSS/Atom feed.")
        add_rss.add_argument("feed_url")
        add_rss.add_argument("--limit", "-n", type=int, default=None)
        add_rss.set_defaults(handler=_handle_add_rss)

        discover_p = sub.add_parser("discover-links", help="Print likely job/application links.")
        discover_p.add_argument("url")
        discover_p.add_argument("--limit", type=int, default=50)
        discover_p.set_defaults(handler=_handle_discover_links)

        search_p = sub.add_parser("search-api", help="Search free/read-only public job APIs.")
        self._add_search_args(search_p)
        search_p.add_argument("--save", action="store_true")
        search_p.set_defaults(handler=_handle_search_api)

        hunt_p = sub.add_parser("hunt", help="Search, import, score, and prepare local packets.")
        self._add_search_args(hunt_p, default_limit=5)
        hunt_p.add_argument("--force", action="store_true")
        hunt_p.set_defaults(handler=_handle_hunt)

        api_p = sub.add_parser("api-sources", help="List supported free/read-only public job API sources.")
        api_p.set_defaults(handler=_handle_api_sources)

        ai_status_p = sub.add_parser("ai-status", help="Check Ollama, LaTeX, Node/npm, Perl, and OpenClaw readiness.")
        ai_status_p.set_defaults(handler=_handle_ai_status)

        smart_plan_p = sub.add_parser("smart-plan", help="Generate a local-AI search query plan.")
        smart_plan_p.add_argument("--query", "-q", default="data scientist")
        smart_plan_p.add_argument("--location", "-l", default="Paris")
        smart_plan_p.add_argument("--language", choices=["english", "french", "both"], default="both")
        smart_plan_p.add_argument("--internships-only", action="store_true", default=True)
        smart_plan_p.add_argument("--all-roles", dest="internships_only", action="store_false")
        smart_plan_p.add_argument("--limit", "-n", type=int, default=8)
        smart_plan_p.set_defaults(handler=_handle_smart_plan)

        multi_p = sub.add_parser("multi-search", help="Search several free/public APIs at once and dedupe results.")
        multi_p.add_argument("--query", "-q", default="data scientist")
        multi_p.add_argument("--location", "-l", default="")
        multi_p.add_argument("--country", default="")
        multi_p.add_argument("--limit", "-n", type=int, default=8, help="Results per source.")
        multi_p.add_argument("--sources", default="", help="Comma-separated source list; default uses all keyword-only sources.")
        multi_p.add_argument("--remote-only", action="store_true")
        multi_p.add_argument("--internships-only", action="store_true")
        multi_p.add_argument("--cache", dest="cache", action="store_true")
        multi_p.add_argument("--no-cache", dest="cache", action="store_false")
        multi_p.set_defaults(cache=True)
        multi_p.add_argument("--save", action="store_true", help="Save deduped results to the local tracker.")
        multi_p.set_defaults(handler=_handle_multi_search)

        ui_p = sub.add_parser("ui", help="Run the local web dashboard.")
        ui_p.add_argument("--host", default="127.0.0.1")
        ui_p.add_argument("--port", type=int, default=8765)
        ui_p.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
        ui_p.set_defaults(handler=_handle_ui)

        fs_p = sub.add_parser("france-setup", help="Show France workflow setup instructions.")
        fs_p.set_defaults(handler=_handle_france_setup)

        wizard_p = sub.add_parser("setup-wizard", help="Interactive wizard to set stage/alternance fields in your QA profile.")
        wizard_p.add_argument("--non-interactive", action="store_true", help="Use default answers without prompting (useful for tests).")
        wizard_p.set_defaults(handler=_handle_setup_wizard)

        gh_p = sub.add_parser("enrich-github", help="Pull skills/repos from your public GitHub and merge into profile JSON.")
        gh_p.add_argument("--handle", default="", help="GitHub username; defaults to contact.github_url in candidate_profile.json.")
        gh_p.add_argument("--no-projects", action="store_true", help="Only update skills; skip adding repos as projects.")
        gh_p.set_defaults(handler=_handle_enrich_github)

        li_p = sub.add_parser("enrich-linkedin", help="Merge a LinkedIn Skills paste (or text file) into profile JSON.")
        li_p.add_argument("--file", default="", help="Optional path to a text file with one skill per line.")
        li_p.set_defaults(handler=_handle_enrich_linkedin)

        export_p = sub.add_parser("export", help="Export tracked internships to the A24 workbook.")
        export_sub = export_p.add_subparsers(dest="export_command")
        export_sub.required = True
        internships_export = export_sub.add_parser("internships", help="Fill the internship tracking workbook with submitted internships.")
        internships_export.add_argument("--workbook", type=Path, default=None, help="Optional workbook path. Defaults to profiles/Internship Search Tracking File A24.xlsx.")
        internships_export.add_argument("--sheet", default=None, help="Optional workbook sheet name.")
        internships_export.set_defaults(handler=_handle_export_internships)

        enrich_p = sub.add_parser("enrich", help="Enrich tracked jobs with France Travail APIs.")
        enrich_p.add_argument("job_id", nargs="?", default="")
        enrich_p.add_argument("--status", default="", help="Enrich jobs by status when job_id is omitted.")
        enrich_p.add_argument("--limit", type=int, default=10)
        enrich_p.add_argument("--rome", action="store_true", help="Use ROME 4.0 endpoints.")
        enrich_p.add_argument("--anotea", action="store_true", help="Use Anotea employer reviews.")
        enrich_p.add_argument("--training", action="store_true", help="Use Open Training endpoints.")
        enrich_p.add_argument("--labour-market", dest="labour_market", action="store_true", help="Use labour market endpoints.")
        enrich_p.add_argument("--territory", action="store_true", help="Use territory endpoints.")
        enrich_p.add_argument("--employer", action="store_true", help="Use employer summary endpoints.")
        enrich_p.add_argument("--other", action="store_true", help="Use remaining France Travail endpoints.")
        enrich_p.set_defaults(handler=_handle_enrich)

        urls_p = sub.add_parser("france-search-urls", help="Print safe manual search URLs for French job boards.")
        urls_p.add_argument("--query", "-q", default="data science stage")
        urls_p.add_argument("--location", "-l", default="Paris")
        urls_p.add_argument("--single-query", action="store_true", help="Do not expand internship/stage/alternance query variants.")
        urls_p.add_argument("--limit", "-n", type=int, default=8, help="Maximum expanded query variants.")
        urls_p.add_argument("--language", choices=["english", "french", "both"], default="both", help="Search query expansion language. Both means English variants first, then French.")
        urls_p.add_argument("--boards", choices=["recommended", "all"], default="recommended", help="Recommended hides brittle/broad boards by default.")
        urls_p.add_argument("--format", choices=["list", "table", "json"], default="list", help="Output format. The default list keeps full URLs copyable.")
        urls_p.add_argument("--output", type=Path, default=None, help="Optional text/JSON file path for the full URL output.")
        urls_p.set_defaults(handler=_handle_france_search_urls)

        targets_p = sub.add_parser("france-targets", help="List CAC 40 / large French company career pages.")
        targets_p.add_argument("--limit", type=int, default=40)
        targets_p.set_defaults(handler=_handle_france_targets)

        fh_p = sub.add_parser("france-hunt", help="France/Paris data-AI hunt using France Travail when configured.")
        fh_p.add_argument("--query", "-q", default="")
        fh_p.add_argument("--location", "-l", default="Paris")
        fh_p.add_argument("--limit", "-n", type=int, default=10)
        fh_p.add_argument("--limit-queries", type=int, default=24)
        fh_p.add_argument("--language", choices=["english", "french", "both"], default="both")
        fh_p.add_argument("--internships-only", action="store_true", help="Keep only internship-like listings from the API results.")
        fh_p.add_argument("--packets", dest="packets", action="store_true")
        fh_p.add_argument("--no-packets", dest="packets", action="store_false")
        fh_p.set_defaults(packets=True)
        fh_p.add_argument("--cache", dest="cache", action="store_true")
        fh_p.add_argument("--no-cache", dest="cache", action="store_false")
        fh_p.set_defaults(cache=True)
        fh_p.add_argument("--force", action="store_true")
        fh_p.set_defaults(handler=_handle_france_hunt)

        list_p = sub.add_parser("list", help="List tracked jobs.")
        list_p.add_argument("--status", "-s", default="")
        list_p.set_defaults(handler=_handle_list)

        show_p = sub.add_parser("show", help="Show details for a job.")
        show_p.add_argument("job_id")
        show_p.set_defaults(handler=_handle_show)

        score_p = sub.add_parser("score", help="Score a job against your candidate profile.")
        score_p.add_argument("job_id")
        score_p.set_defaults(handler=_handle_score)

        apply_p = sub.add_parser("apply", help="Generate a full local application packet.")
        apply_p.add_argument("job_id")
        apply_p.add_argument("--force", action="store_true")
        apply_p.set_defaults(handler=_handle_apply)

        process_p = sub.add_parser("process", help="One-command job processing.")
        process_sub = process_p.add_subparsers(dest="process_command")
        process_sub.required = True
        process_file_p = process_sub.add_parser("file", help="Process a job description file end to end.")
        process_file_p.add_argument("path", type=Path)
        process_file_p.add_argument("--title", default="")
        process_file_p.add_argument("--company", default="")
        process_file_p.add_argument("--url", default="")
        process_file_p.add_argument("--force", action="store_true")
        process_file_p.set_defaults(handler=_handle_process_file)

        status_p = sub.add_parser("status", help="Update the status of a job.")
        status_p.add_argument("job_id")
        status_p.add_argument("new_status")
        status_p.add_argument("--note", "-n", default="")
        status_p.set_defaults(handler=_handle_status)

        history_p = sub.add_parser("history", help="Show event history for a job.")
        history_p.add_argument("job_id")
        history_p.set_defaults(handler=_handle_history)

        assist_p = sub.add_parser("apply-assist", help="Open the local assistant page and apply URL.")
        assist_p.add_argument("packet_id")
        assist_p.add_argument("--open-browser", dest="open_browser", action="store_true")
        assist_p.add_argument("--no-open-browser", dest="open_browser", action="store_false")
        assist_p.set_defaults(open_browser=True, handler=_handle_apply_assist)

        submitted_p = sub.add_parser("mark-submitted", help="Mark an application packet as manually submitted.")
        submitted_p.add_argument("packet_id")
        submitted_p.add_argument("--note", "-n", default="")
        submitted_p.set_defaults(handler=_handle_mark_submitted)

        packet_p = sub.add_parser("packet", help="Manage application packets.")
        packet_sub = packet_p.add_subparsers(dest="packet_command")
        packet_sub.required = True
        packet_show = packet_sub.add_parser("show", help="Show a packet by job or packet id.")
        packet_show.add_argument("job_or_packet_id")
        packet_show.set_defaults(handler=_handle_packet_show)

        return parser

    def _add_search_args(self, parser: argparse.ArgumentParser, default_limit: int = 10) -> None:
        parser.add_argument("source")
        parser.add_argument("--query", "-q", default="")
        parser.add_argument("--location", "-l", default="")
        parser.add_argument("--country", default="")
        parser.add_argument("--board", default="")
        parser.add_argument("--limit", "-n", type=int, default=default_limit)
        parser.add_argument("--page", type=int, default=1)
        parser.add_argument("--remote-only", action="store_true")
        parser.add_argument("--internships-only", action="store_true")
        parser.add_argument("--cache", dest="cache", action="store_true")
        parser.add_argument("--no-cache", dest="cache", action="store_false")
        parser.set_defaults(cache=True)
        parser.add_argument("--cache-ttl-hours", type=float, default=6.0)

    def invoke(self, argv: list[str] | None = None) -> int:
        parser = self.build_parser()
        argv = list(argv or [])
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:
            return int(exc.code or 0)

        handler = getattr(args, "handler", None)
        if handler is None:
            parser.print_help()
            return 1
        try:
            handler(args)
            return 0
        except CLIError as exc:
            console.print(exc.message)
            return exc.code

    def __call__(self) -> None:  # pragma: no cover
        raise SystemExit(self.invoke(sys.argv[1:]))


app = LocalCLIApp()


if __name__ == "__main__":  # pragma: no cover
    app()
