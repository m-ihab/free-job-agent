"""Service helpers for the local web UI.

The UI is intentionally thin: these helpers call the same backend functions as
the CLI so the browser dashboard and command line stay behaviorally aligned.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.generator.company_extract import extract_real_company, looks_unusable_company
from job_agent.intake.france_market import board_notes, build_france_search_urls, expand_france_search_queries
from job_agent.intake.france_travail_endpoints import load_endpoint_base_url, load_endpoint_registry
from job_agent.notifier import email_notifier_status
from job_agent.polish import PolishOptions, is_ollama_enabled_and_reachable, ollama_status
from job_agent.renderer.latex_render import available_latex_compiler
from job_agent.search_quality import assess_search_quality
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket
from job_agent.validators import validate_profile_bundle
from job_agent.work_auth import check_gratification, classify_work_auth


APP_NAME = os.environ.get("JOB_AGENT_APP_NAME", "Career Copilot")
APP_URL_PLACEHOLDER = os.environ.get(
    "JOB_AGENT_APP_URL",
    "https://github.com/your-username/free-job-agent",
)
APP_DESCRIPTION = os.environ.get(
    "JOB_AGENT_APP_DESCRIPTION",
    "A local-first career copilot for data science, AI, and analytics roles in France. "
    "It searches public job data, tracks opportunities, scores fit against my profile, "
    "and prepares tailored CV and cover-letter packets for manual review and submission.",
)


def configured_app() -> AppConfig:
    config = AppConfig.load()
    config.ensure_dirs()
    Database(config.db_path).initialize()  # type: ignore[arg-type]
    return config


def is_france_travail_configured() -> bool:
    return bool(os.environ.get("FRANCE_TRAVAIL_CLIENT_ID") and os.environ.get("FRANCE_TRAVAIL_CLIENT_SECRET"))


def latex_compiler() -> str | None:
    compiler = available_latex_compiler()
    return Path(compiler).name if compiler else None


def _tool_path(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    appdata = Path.home() / "AppData" / "Roaming"
    program_files = Path("C:/Program Files")
    candidates = {
        "perl": [Path("C:/Strawberry/perl/bin/perl.exe"), Path("C:/Perl64/bin/perl.exe")],
        "npm": [program_files / "nodejs" / "npm.cmd", appdata / "npm" / "npm.cmd"],
        "openclaw": [appdata / "npm" / "openclaw.cmd", appdata / "npm" / "openclaw.ps1"],
    }.get(name, [])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def profile_status(config: AppConfig | None = None) -> dict[str, Any]:
    config = config or configured_app()
    report = validate_profile_bundle(config)
    compiler = latex_compiler()
    env_path = Path(os.environ.get("JOB_AGENT_ENV_FILE", "") or Path.cwd() / ".env.local").expanduser()
    endpoints_path = Path(os.environ.get("FRANCE_TRAVAIL_ENDPOINTS_FILE", "") or Path.cwd() / ".france_travail.endpoints.local.json").expanduser()
    registry = load_endpoint_registry()
    endpoint_total = len(registry)
    endpoint_configured = sum(1 for spec in registry.values() if spec.path)
    endpoint_enabled = sum(1 for spec in registry.values() if spec.enabled and spec.path)
    polish_options = PolishOptions.from_env()
    ollama = ollama_status(polish_options)
    notifier = email_notifier_status()
    ollama_ready = bool(ollama["reachable"])
    france_travail_ready = is_france_travail_configured()
    apprentissage_ready = bool(os.environ.get("APPRENTISSAGE_API_TOKEN") or os.environ.get("LABONNEALTERNANCE_API_TOKEN"))
    return {
        "valid": not report.errors,
        "errors": report.errors,
        "warnings": report.warnings,
        "profiles_dir": str(config.profiles_dir),
        "data_dir": str(config.data_dir),
        "outputs_dir": str(config.outputs_dir),
        "france_travail_configured": france_travail_ready,
        "apprentissage_configured": apprentissage_ready,
        "env_local_present": env_path.exists(),
        "endpoints_file_present": endpoints_path.exists(),
        "endpoints_file": str(endpoints_path) if endpoints_path.exists() else "",
        # The endpoints map is OPTIONAL — only needed for enrichment APIs
        # (ROME 4.0, Anotea, Open Training, Labour Market). Basic job search
        # works with just the client_id/secret credentials.
        "endpoints_optional": True,
        "endpoints_explainer": (
            "The endpoints map is only required for advanced enrichment APIs "
            "(ROME 4.0 skills, Anotea reviews, Open Training, Labour Market). "
            "With just FRANCE_TRAVAIL_CLIENT_ID and FRANCE_TRAVAIL_CLIENT_SECRET, "
            "the core job search already works."
        ),
        "search_ready": france_travail_ready,
        "alternance_search_ready": apprentissage_ready,
        "enrichment_ready": france_travail_ready and endpoints_path.exists(),
        "endpoints_summary": {
            "total": endpoint_total,
            "configured": endpoint_configured,
            "enabled": endpoint_enabled,
            "base_url": load_endpoint_base_url(),
        },
        "latex_compiler": compiler,
        "latex_ready": compiler is not None,
        "ollama_enabled": polish_options.enabled,
        "ollama_ready": ollama_ready,
        "ollama_model": ollama["selected_model"] if ollama_ready else polish_options.model,
        "ollama_models": ollama["models"],
        "ollama_polish_enabled": is_ollama_enabled_and_reachable(polish_options),
        "email_notifier": notifier,
        "local_tools": {
            "perl": _tool_path("perl"),
            "npm": _tool_path("npm"),
            "openclaw": _tool_path("openclaw"),
        },
        "app_name": APP_NAME,
        "app_description": APP_DESCRIPTION,
        "app_url": APP_URL_PLACEHOLDER,
    }


def build_manual_search_groups(
    query: str,
    location: str = "Paris",
    language: str = "both",
    limit: int = 8,
    boards: str = "recommended",
) -> list[dict[str, Any]]:
    recommended_only = boards != "all"
    queries = expand_france_search_queries(query, limit=limit, language=language)
    notes = board_notes()
    groups: list[dict[str, Any]] = []
    for expanded_query in queries:
        links = []
        for key, name, url in build_france_search_urls(expanded_query, location, recommended_only=recommended_only):
            links.append({"board_key": key, "board": name, "url": url, "note": notes.get(key, "")})
        groups.append({"query": expanded_query, "links": links})
    return groups


def _read_latex_warning(packet: "ApplicationPacket | None") -> str:
    if packet is None:
        return ""
    art = next((a for a in packet.artifacts if a.kind == "latex_warning"), None)
    if art is None:
        return ""
    try:
        return Path(art.path).read_text(encoding="utf-8")
    except Exception:
        return ""


def job_to_dict(
    job: JobListing,
    latest_packet: ApplicationPacket | None = None,
    enrichment: dict | None = None,
    ai_cache: dict | None = None,
    profile: Any | None = None,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    enrichment = enrichment or {}
    enrichment_sources = enrichment.get("sources") or {}
    anotea = enrichment.get("anotea") or {}
    ai_cache = ai_cache or {}
    ai_fit = ai_cache.get("fit") or {}
    ai_summary = ai_cache.get("summary") or {}
    ai_classify = ai_cache.get("classify") or {}
    quality = assess_search_quality(job)
    company_display = job.company
    company_source = ""
    company_unresolved = False
    if looks_unusable_company(job.company):
        real_company = extract_real_company(job)
        if real_company:
            company_display = real_company
            company_source = job.company
        else:
            company_display = "Employer not disclosed"
            company_source = job.company
            company_unresolved = True
    work_auth = classify_work_auth(job, profile) if profile is not None else None
    gratification = check_gratification(job, config) if config is not None else None
    return {
        "id": job.id,
        "short_id": job.id[:8],
        "title": job.title,
        "company": job.company,
        "company_display": company_display,
        "company_source": company_source,
        "company_unresolved": company_unresolved,
        "location": job.location or "",
        "remote": job.remote,
        "work_mode": job.work_mode or "",
        "job_type": job.job_type or "",
        "source": job.source,
        "apply_url": job.apply_url or job.source_url or "",
        "status": job.status.value,
        "fit_score": job.fit_score,
        "fit_decision": job.fit_decision or "",
        "fit_notes": job.fit_notes,
        "missing_requirements": job.missing_requirements,
        "tech_stack": job.tech_stack,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "latest_packet_id": latest_packet.id if latest_packet else "",
        "latest_packet_status": latest_packet.status.value if latest_packet else "",
        "cv_pdf": latest_packet.tailored_cv_pdf_path if latest_packet else "",
        "cover_letter_pdf": latest_packet.cover_letter_pdf_path if latest_packet else "",
        "assistant_page": next((artifact.path for artifact in latest_packet.artifacts if artifact.kind == "assistant_html"), "") if latest_packet else "",
        "enriched": bool(enrichment_sources),
        "enrichment_updated_at": enrichment.get("updated_at") or "",
        "enrichment_sources": enrichment_sources,
        "anotea_rating": anotea.get("rating"),
        "rome_skills": (enrichment.get("rome_skills") or [])[:10],
        "training_recommendations": (enrichment.get("training_recommendations") or [])[:8],
        "labour_market_signals": (enrichment.get("labour_market_signals") or [])[:8],
        "ai_verdict": ai_fit.get("verdict") or "",
        "ai_score": ai_fit.get("score"),
        "ai_summary": ai_summary.get("tldr") or "",
        "ai_key_signals": ai_summary.get("key_signals") or [],
        "ai_tags": ai_classify.get("tags") or [],
        "ai_role_family": ai_classify.get("role_family") or quality.get("role_family") or "",
        "ai_seniority": ai_classify.get("seniority") or "",
        "ai_contract": ai_classify.get("contract") or quality.get("contract") or "",
        "ai_remote_mode": ai_classify.get("remote_mode") or "",
        "ai_must_haves": ai_classify.get("must_haves") or [],
        "ai_nice_to_haves": ai_classify.get("nice_to_haves") or [],
        "search_quality_score": getattr(job, "search_quality_score", None) or quality.get("score"),
        "search_quality_flags": getattr(job, "search_quality_flags", None) or quality.get("flags") or [],
        "search_role_family": getattr(job, "search_role_family", None) or quality.get("role_family") or "",
        "search_contract": getattr(job, "search_contract", None) or quality.get("contract") or "",
        "risk_flags": job.risk_flags or [],
        "latex_warning": _read_latex_warning(latest_packet),
        "work_auth_class": work_auth.work_auth_class.value if work_auth else "",
        "work_auth_contract": work_auth.contract_kind.value if work_auth else "",
        "work_auth_blocking": work_auth.blocking if work_auth else False,
        "work_auth_rationale": work_auth.rationale if work_auth else "",
        "work_auth_notes": work_auth.notes if work_auth else [],
        "gratification_warning": {
            "flagged": gratification.flagged if gratification else False,
            "reason": gratification.reason if gratification else "",
            "threshold": gratification.threshold if gratification else None,
            "observed": gratification.observed if gratification else None,
        },
    }


def packet_to_dict(packet: ApplicationPacket) -> dict[str, Any]:
    latex_warning_art = next((a for a in packet.artifacts if a.kind == "latex_warning"), None)
    latex_warning_text = ""
    if latex_warning_art:
        try:
            latex_warning_text = Path(latex_warning_art.path).read_text(encoding="utf-8")
        except Exception:
            pass
    return {
        "id": packet.id,
        "job_id": packet.job_id,
        "status": packet.status.value,
        "fit_score": packet.fit_score,
        "fit_decision": packet.fit_decision,
        "headline": getattr(packet, "headline", "") or "",
        "summary": getattr(packet, "summary", "") or "",
        "keywords": getattr(packet, "keywords", []) or [],
        "cv_pdf": packet.tailored_cv_pdf_path or "",
        "cover_letter_pdf": packet.cover_letter_pdf_path or "",
        "assistant_page": next((artifact.path for artifact in packet.artifacts if artifact.kind == "assistant_html"), ""),
        "artifacts": [artifact.dict() for artifact in packet.artifacts],
        "latex_warning": latex_warning_text,
    }


def status_options() -> list[str]:
    return [status.value for status in JobStatus]
