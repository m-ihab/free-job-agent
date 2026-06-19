"""Profile setup, validation, enrichment, and audit command handlers."""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
from pathlib import Path

from job_agent.config import AppConfig
from job_agent.cv_template import import_cv_template_upload
from job_agent.db.database import Database
from job_agent.profile_audit import audit_profile
from job_agent.profile_enrich import (
    enrich_from_github,
    enrich_from_linkedin_skills,
)
from job_agent.validators import load_profile_bundle, validate_profile_bundle

from job_agent.cli.commands._common import (
    Panel,
    _WIZARD_STEPS,
    _fail,
    _find_examples_dir,
    _get_tracker,
    _load_config,
    console,
)


def _handle_init(args: argparse.Namespace) -> None:
    config = AppConfig()
    config.ensure_dirs()
    config.save()
    Database(config.db_path).initialize()  # type: ignore[arg-type]
    console.print(f"Initialized job-agent data directory at: {config.data_dir}")
    console.print(f"Place profile files in: {config.profiles_dir}")


def _handle_copy_examples(args: argparse.Namespace) -> None:
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


def _handle_validate_profile(args: argparse.Namespace) -> None:
    report = validate_profile_bundle(_load_config())
    if report.errors:
        console.print("Profile validation failed")
        for err in report.errors:
            console.print(f"  - {err}")
        _fail("Profile validation failed", code=1)
    console.print("Profile validation passed")
    for warning in report.warnings:
        console.print(f"Warning: {warning}")


def _handle_enrich_github(args: argparse.Namespace) -> None:
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


def _handle_enrich_linkedin(args: argparse.Namespace) -> None:
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


def _handle_setup_wizard(args: argparse.Namespace) -> None:
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


def _handle_import_cv_template(args: argparse.Namespace) -> None:
    config = _load_config()
    config.ensure_dirs()
    path = Path(args.path)
    if not path.exists() or not path.is_file():
        _fail(f"Template file not found: {path}")
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    try:
        result = import_cv_template_upload(config, filename=path.name, content_base64=payload)
    except Exception as exc:
        _fail(f"Could not import CV template: {exc}")
    console.print(
        Panel(
            f"{result['note']}\nStored at: {result['target']}\nBackups: {', '.join(result['backups']) or '-'}",
            title="CV template imported",
        )
    )


def _handle_audit_profile(args: argparse.Namespace) -> None:
    """Run strict recruiter audit on the profile and save a report."""
    config = _load_config()
    profile, master_cv, _ = load_profile_bundle(config)
    tracker = _get_tracker(config)
    tracked_jobs = tracker.list_jobs(limit=None)
    report = audit_profile(profile, master_cv, tracked_jobs)
    md = report.to_markdown()
    console.print(md)
    # Save to profiles dir
    if config.profiles_dir:
        report_path = config.profiles_dir / "profile_audit_report.md"
        report_path.write_text(md, encoding="utf-8")
        console.print(f"\n[dim]Saved to {report_path}[/dim]")


def _handle_suggest_skills(args: argparse.Namespace) -> None:
    """Suggest implied and trending skills to add to the profile."""
    from job_agent.skill_extractor import extract_implied_skills, suggest_trend_gaps
    config = _load_config()
    profile, master_cv, _ = load_profile_bundle(config)
    implied = extract_implied_skills(profile, master_cv)
    trends = suggest_trend_gaps(profile)
    if implied:
        console.print("\n[bold]Implied skills (from your experience):[/bold]")
        for s in implied[:15]:
            console.print(f"  • {s.name}  [dim](from {s.implied_by})[/dim]")
    if trends:
        console.print("\n[bold]2025 trending skills not in your profile:[/bold]")
        for t in trends[:10]:
            console.print(f"  • {t}")
    if not implied and not trends:
        console.print("Your profile looks complete — no implied or trending gaps found.")
