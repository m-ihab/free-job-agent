"""Local-first CLI for free-job-agent.

This module intentionally uses the Python standard library for argument
parsing so the core workflow still works in environments where Click is not
available. Tests continue to use a tiny local ``click.testing`` shim.

The per-command handler callables live in :mod:`job_agent.cli.commands`,
grouped by domain. This module owns argument-parser construction and the
``app``/``main`` entry points, importing the handlers lazily inside
:meth:`LocalCLIApp.build_parser` to avoid an import cycle with the command
modules (which import shared helpers and ``search_free_api_jobs`` re-exported
here).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Re-exported so tests can monkeypatch ``job_agent.cli.main.search_free_api_jobs``
# and so the search/france handlers can resolve it from this module at call time.
from job_agent.intake.free_apis import (  # noqa: F401 - re-exported for patching
    FreeApiError,
    KEYWORD_ONLY_SOURCES,
    search_all_free_sources,
    search_free_api_jobs,
    supported_source_names,
)

from job_agent.cli.commands._common import CLIError, console

__all__ = ["app", "main", "LocalCLIApp", "CLIError", "console", "search_free_api_jobs"]


class LocalCLIApp:
    prog = "job-agent"

    def build_parser(self) -> argparse.ArgumentParser:
        from job_agent.cli.commands import apply as apply_cmds
        from job_agent.cli.commands import france as france_cmds
        from job_agent.cli.commands import jobs as job_cmds
        from job_agent.cli.commands import outreach as outreach_cmds
        from job_agent.cli.commands import profile as profile_cmds
        from job_agent.cli.commands import search as search_cmds
        from job_agent.cli.commands import system as system_cmds

        parser = argparse.ArgumentParser(prog=self.prog, description="Free, local-first job-search and application assistant.")
        sub = parser.add_subparsers(dest="command")
        sub.required = True

        init_p = sub.add_parser("init", help="Initialize data directory and config.")
        init_p.set_defaults(handler=profile_cmds._handle_init)

        copy_p = sub.add_parser("copy-examples", help="Copy example profile files.")
        copy_p.set_defaults(handler=profile_cmds._handle_copy_examples)

        validate_p = sub.add_parser("validate-profile", help="Validate candidate profile files.")
        validate_p.set_defaults(handler=profile_cmds._handle_validate_profile)

        add_p = sub.add_parser("add", help="Add jobs from various sources.")
        add_sub = add_p.add_subparsers(dest="add_command")
        add_sub.required = True

        add_paste = add_sub.add_parser("paste", help="Add a job from stdin paste mode.")
        add_paste.add_argument("--title", default="")
        add_paste.add_argument("--company", default="")
        add_paste.add_argument("--url", default="")
        add_paste.set_defaults(handler=job_cmds._handle_add_paste)

        add_file = add_sub.add_parser("file", help="Add a job from a text/markdown file.")
        add_file.add_argument("path", type=Path)
        add_file.add_argument("--title", default="")
        add_file.add_argument("--company", default="")
        add_file.add_argument("--url", default="")
        add_file.set_defaults(handler=job_cmds._handle_add_file)

        add_url = add_sub.add_parser("url", help="Add a job from a public URL.")
        add_url.add_argument("url")
        add_url.set_defaults(handler=job_cmds._handle_add_url)

        add_rss = add_sub.add_parser("rss", help="Add jobs from an RSS/Atom feed.")
        add_rss.add_argument("feed_url")
        add_rss.add_argument("--limit", "-n", type=int, default=None)
        add_rss.set_defaults(handler=search_cmds._handle_add_rss)

        obsidian_p = sub.add_parser(
            "obsidian-sync",
            help="Export the local job DB into a linked Obsidian vault (graph + dashboard).",
        )
        obsidian_p.add_argument(
            "--vault", default=None,
            help="Vault directory (default: ./second-brain or config.obsidian_vault_dir).",
        )
        obsidian_p.set_defaults(handler=job_cmds._handle_obsidian_sync)

        discover_p = sub.add_parser("discover-links", help="Print likely job/application links.")
        discover_p.add_argument("url")
        discover_p.add_argument("--limit", type=int, default=50)
        discover_p.set_defaults(handler=search_cmds._handle_discover_links)

        search_p = sub.add_parser("search-api", help="Search free/read-only public job APIs.")
        self._add_search_args(search_p)
        search_p.add_argument("--save", action="store_true")
        search_p.set_defaults(handler=search_cmds._handle_search_api)

        hunt_p = sub.add_parser("hunt", help="Search, import, score, and prepare local packets.")
        self._add_search_args(hunt_p, default_limit=5)
        hunt_p.add_argument("--force", action="store_true")
        hunt_p.set_defaults(handler=search_cmds._handle_hunt)

        api_p = sub.add_parser("api-sources", help="List supported free/read-only public job API sources.")
        api_p.set_defaults(handler=search_cmds._handle_api_sources)

        ai_status_p = sub.add_parser("ai-status", help="Check Ollama, LaTeX, Node/npm, Perl, and OpenClaw readiness.")
        ai_status_p.set_defaults(handler=system_cmds._handle_ai_status)

        smart_plan_p = sub.add_parser("smart-plan", help="Generate a local-AI search query plan.")
        smart_plan_p.add_argument("--query", "-q", default="data scientist")
        smart_plan_p.add_argument("--location", "-l", default="Paris")
        smart_plan_p.add_argument("--language", choices=["english", "french", "both"], default="both")
        smart_plan_p.add_argument("--internships-only", action="store_true", default=True)
        smart_plan_p.add_argument("--all-roles", dest="internships_only", action="store_false")
        smart_plan_p.add_argument("--limit", "-n", type=int, default=8)
        smart_plan_p.set_defaults(handler=search_cmds._handle_smart_plan)

        multi_p = sub.add_parser("multi-search", help="Search several free/public APIs at once and dedupe results.")
        multi_p.add_argument("--query", "-q", default="data scientist")
        multi_p.add_argument("--location", "-l", default="")
        multi_p.add_argument("--country", default="")
        multi_p.add_argument("--limit", "-n", type=int, default=8, help="Results per source.")
        multi_p.add_argument("--sources", default="", help="Comma-separated source list; default uses all keyword-only sources.")
        multi_p.add_argument("--remote-only", action="store_true")
        multi_p.add_argument("--internships-only", action="store_true")
        multi_p.add_argument("--min-relevance", type=int, default=50, help="Drop obvious noise below this search-quality score; use 0 for broad mode.")
        multi_p.add_argument("--france-eu-only", action="store_true", default=True, help="Keep France/EU/remote-compatible results.")
        multi_p.add_argument("--worldwide", dest="france_eu_only", action="store_false", help="Allow worldwide/non-EU locations.")
        multi_p.add_argument("--radius-km", type=int, default=0, help="France Travail-style radius hint when supported.")
        multi_p.add_argument("--cache", dest="cache", action="store_true")
        multi_p.add_argument("--no-cache", dest="cache", action="store_false")
        multi_p.set_defaults(cache=True)
        multi_p.add_argument("--save", action="store_true", help="Save deduped results to the local tracker.")
        multi_p.set_defaults(handler=search_cmds._handle_multi_search)

        ui_p = sub.add_parser("ui", help="Run the local web dashboard.")
        ui_p.add_argument("--host", default="127.0.0.1")
        ui_p.add_argument("--port", type=int, default=8765)
        ui_p.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
        ui_p.set_defaults(handler=system_cmds._handle_ui)

        fs_p = sub.add_parser("france-setup", help="Show France workflow setup instructions.")
        fs_p.set_defaults(handler=france_cmds._handle_france_setup)

        wizard_p = sub.add_parser("setup-wizard", help="Interactive wizard to set stage/alternance fields in your QA profile.")
        wizard_p.add_argument("--non-interactive", action="store_true", help="Use default answers without prompting (useful for tests).")
        wizard_p.set_defaults(handler=profile_cmds._handle_setup_wizard)

        gh_p = sub.add_parser("enrich-github", help="Pull skills/repos from your public GitHub and merge into profile JSON.")
        gh_p.add_argument("--handle", default="", help="GitHub username; defaults to contact.github_url in candidate_profile.json.")
        gh_p.add_argument("--no-projects", action="store_true", help="Only update skills; skip adding repos as projects.")
        gh_p.set_defaults(handler=profile_cmds._handle_enrich_github)

        li_p = sub.add_parser("enrich-linkedin", help="Merge a LinkedIn Skills paste (or text file) into profile JSON.")
        li_p.add_argument("--file", default="", help="Optional path to a text file with one skill per line.")
        li_p.set_defaults(handler=profile_cmds._handle_enrich_linkedin)

        export_p = sub.add_parser("export", help="Export tracked internships to a workbook.")
        export_sub = export_p.add_subparsers(dest="export_command")
        export_sub.required = True
        internships_export = export_sub.add_parser("internships", help="Fill the internship tracking workbook with submitted internships.")
        internships_export.add_argument("--workbook", type=Path, default=None, help="Optional workbook path. Defaults to profiles/internship_tracker.xlsx (or your existing private workbook if present).")
        internships_export.add_argument("--sheet", default=None, help="Optional workbook sheet name.")
        internships_export.set_defaults(handler=system_cmds._handle_export_internships)

        cv_template_p = sub.add_parser("import-cv-template", help="Import a local CV template/photo into the git-ignored profiles folder.")
        cv_template_p.add_argument("path", type=Path)
        cv_template_p.set_defaults(handler=profile_cmds._handle_import_cv_template)

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
        enrich_p.set_defaults(handler=job_cmds._handle_enrich)

        urls_p = sub.add_parser("france-search-urls", help="Print safe manual search URLs for French job boards.")
        urls_p.add_argument("--query", "-q", default="data science stage")
        urls_p.add_argument("--location", "-l", default="Paris")
        urls_p.add_argument("--single-query", action="store_true", help="Do not expand internship/stage/alternance query variants.")
        urls_p.add_argument("--limit", "-n", type=int, default=8, help="Maximum expanded query variants.")
        urls_p.add_argument("--language", choices=["english", "french", "both"], default="both", help="Search query expansion language. Both means English variants first, then French.")
        urls_p.add_argument("--boards", choices=["recommended", "all"], default="recommended", help="Recommended hides brittle/broad boards by default.")
        urls_p.add_argument("--format", choices=["list", "table", "json"], default="list", help="Output format. The default list keeps full URLs copyable.")
        urls_p.add_argument("--output", type=Path, default=None, help="Optional text/JSON file path for the full URL output.")
        urls_p.set_defaults(handler=france_cmds._handle_france_search_urls)

        targets_p = sub.add_parser("france-targets", help="List CAC 40 / large French company career pages.")
        targets_p.add_argument("--limit", type=int, default=40)
        targets_p.set_defaults(handler=france_cmds._handle_france_targets)

        fh_p = sub.add_parser("france-hunt", help="France/Paris data-AI hunt using France Travail when configured.")
        fh_p.add_argument("--query", "-q", default="")
        fh_p.add_argument("--location", "-l", default="Paris")
        fh_p.add_argument("--limit", "-n", type=int, default=10)
        fh_p.add_argument("--limit-queries", type=int, default=24)
        fh_p.add_argument("--language", choices=["english", "french", "both"], default="both")
        fh_p.add_argument("--internships-only", action="store_true", help="Keep only internship-like listings from the API results.")
        fh_p.add_argument("--min-relevance", type=int, default=50, help="Drop obvious noise below this search-quality score; use 0 for broad mode.")
        fh_p.add_argument("--france-eu-only", action="store_true", default=True, help="Keep France/EU results.")
        fh_p.add_argument("--worldwide", dest="france_eu_only", action="store_false", help="Allow worldwide/non-EU locations.")
        fh_p.add_argument("--radius-km", type=int, default=25, help="Radius around Paris when location is Paris (0 disables radius).")
        fh_p.add_argument("--packets", dest="packets", action="store_true")
        fh_p.add_argument("--no-packets", dest="packets", action="store_false")
        fh_p.set_defaults(packets=True)
        fh_p.add_argument("--cache", dest="cache", action="store_true")
        fh_p.add_argument("--no-cache", dest="cache", action="store_false")
        fh_p.set_defaults(cache=True)
        fh_p.add_argument("--force", action="store_true")
        fh_p.set_defaults(handler=france_cmds._handle_france_hunt)

        list_p = sub.add_parser("list", help="List tracked jobs.")
        list_p.add_argument("--status", "-s", default="")
        list_p.set_defaults(handler=job_cmds._handle_list)

        show_p = sub.add_parser("show", help="Show details for a job.")
        show_p.add_argument("job_id")
        show_p.set_defaults(handler=job_cmds._handle_show)

        score_p = sub.add_parser("score", help="Score a job against your candidate profile.")
        score_p.add_argument("job_id")
        score_p.set_defaults(handler=job_cmds._handle_score)

        apply_p = sub.add_parser("apply", help="Generate a full local application packet.")
        apply_p.add_argument("job_id")
        apply_p.add_argument("--force", action="store_true")
        apply_p.set_defaults(handler=apply_cmds._handle_apply)

        process_p = sub.add_parser("process", help="One-command job processing.")
        process_sub = process_p.add_subparsers(dest="process_command")
        process_sub.required = True
        process_file_p = process_sub.add_parser("file", help="Process a job description file end to end.")
        process_file_p.add_argument("path", type=Path)
        process_file_p.add_argument("--title", default="")
        process_file_p.add_argument("--company", default="")
        process_file_p.add_argument("--url", default="")
        process_file_p.add_argument("--force", action="store_true")
        process_file_p.set_defaults(handler=apply_cmds._handle_process_file)

        status_p = sub.add_parser("status", help="Update the status of a job.")
        status_p.add_argument("job_id")
        status_p.add_argument("new_status")
        status_p.add_argument("--note", "-n", default="")
        status_p.set_defaults(handler=job_cmds._handle_status)

        delete_p = sub.add_parser("delete-job", help="Remove a job from the local tracker.")
        delete_p.add_argument("job_id")
        delete_p.add_argument("--yes", action="store_true", help="Confirm deletion.")
        delete_p.add_argument("--note", default="")
        delete_p.set_defaults(handler=job_cmds._handle_delete_job)

        history_p = sub.add_parser("history", help="Show event history for a job.")
        history_p.add_argument("job_id")
        history_p.set_defaults(handler=job_cmds._handle_history)

        assist_p = sub.add_parser("apply-assist", help="Open the local assistant page and apply URL.")
        assist_p.add_argument("packet_id")
        assist_p.add_argument("--open-browser", dest="open_browser", action="store_true")
        assist_p.add_argument("--no-open-browser", dest="open_browser", action="store_false")
        assist_p.set_defaults(open_browser=True, handler=apply_cmds._handle_apply_assist)

        submitted_p = sub.add_parser("mark-submitted", help="Mark an application packet as manually submitted.")
        submitted_p.add_argument("packet_id")
        submitted_p.add_argument("--note", "-n", default="")
        submitted_p.set_defaults(handler=apply_cmds._handle_mark_submitted)

        outreach_p = sub.add_parser("outreach", help="Draft a recruiter outreach email for a job and print it.")
        outreach_p.add_argument("job_id", help="Job ID or short ID.")
        outreach_p.set_defaults(handler=outreach_cmds._handle_outreach)

        linkedin_p = sub.add_parser("linkedin-message", help="Generate a LinkedIn message for a job (connect/recruiter/followup).")
        linkedin_p.add_argument("job_id", help="Job ID or short ID.")
        linkedin_p.add_argument("--type", choices=["connect", "recruiter", "followup"], default="recruiter")
        linkedin_p.set_defaults(handler=outreach_cmds._handle_linkedin_message)

        audit_p = sub.add_parser("audit-profile", help="Strict recruiter audit: why you'd get rejected and how to fix it.")
        audit_p.set_defaults(handler=profile_cmds._handle_audit_profile)

        suggest_skills_p = sub.add_parser("suggest-skills", help="Suggest implied and trending skills to add to your profile.")
        suggest_skills_p.set_defaults(handler=profile_cmds._handle_suggest_skills)

        market_p = sub.add_parser("market-report", help="Job market intelligence from your tracked jobs.")
        market_p.add_argument("--output", type=Path, default=None, help="Save report to file.")
        market_p.set_defaults(handler=outreach_cmds._handle_market_report)

        interview_p = sub.add_parser("interview-prep", help="Generate interview prep questions for a job.")
        interview_p.add_argument("job_id", help="Job ID or short ID.")
        interview_p.add_argument("--save", action="store_true", default=False, help="Save to packet folder.")
        interview_p.set_defaults(handler=outreach_cmds._handle_interview_prep)

        followup_p = sub.add_parser("followup-email", help="Generate a follow-up email after applying.")
        followup_p.add_argument("job_id", help="Job ID or short ID.")
        followup_p.add_argument("--type", choices=["week1", "week2", "rejection"], default="week1")
        followup_p.set_defaults(handler=outreach_cmds._handle_followup_email)

        hh_p = sub.add_parser("headhunter", help="Proactive outreach tools — batch messages, English-first strategy.")
        hh_sub = hh_p.add_subparsers(dest="hh_command")
        hh_sub.required = True

        hh_batch = hh_sub.add_parser("batch", help="Generate outreach packs for all high-scoring jobs.")
        hh_batch.add_argument("--min-score", type=int, default=65, help="Minimum fit score threshold (default 65).")
        hh_batch.add_argument("--english-first", action="store_true", help="Only include English-first companies.")
        hh_batch.add_argument("--output", type=Path, default=None, help="Output markdown file path.")
        hh_batch.set_defaults(handler=outreach_cmds._handle_headhunter_batch)

        hh_strategy = hh_sub.add_parser("strategy", help="Show English-first company strategy for your tracked jobs.")
        hh_strategy.add_argument("--output", type=Path, default=None, help="Optional file to save the report.")
        hh_strategy.set_defaults(handler=outreach_cmds._handle_headhunter_strategy)

        packet_p = sub.add_parser("packet", help="Manage application packets.")
        packet_sub = packet_p.add_subparsers(dest="packet_command")
        packet_sub.required = True
        packet_show = packet_sub.add_parser("show", help="Show a packet by job or packet id.")
        packet_show.add_argument("job_or_packet_id")
        packet_show.set_defaults(handler=apply_cmds._handle_packet_show)

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
        parser.add_argument("--min-relevance", type=int, default=0, help="Drop obvious noise below this search-quality score; 50 is a good refined mode.")
        parser.add_argument("--france-eu-only", action="store_true", help="Keep France/EU/remote-compatible results.")
        parser.add_argument("--radius-km", type=int, default=0, help="Radius around Paris when France Travail supports commune/distance search.")
        parser.add_argument("--cache", dest="cache", action="store_true")
        parser.add_argument("--no-cache", dest="cache", action="store_false")
        parser.set_defaults(cache=True)
        parser.add_argument("--cache-ttl-hours", type=float, default=6.0)

    def invoke(self, argv: list[str] | None = None) -> int:
        from job_agent.logging_config import configure_logging
        configure_logging()
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


def main() -> None:  # pragma: no cover - convenience entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    app()
