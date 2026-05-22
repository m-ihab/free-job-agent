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
from job_agent.intake.france_market import board_notes, build_france_search_urls, expand_france_search_queries
from job_agent.schemas.job import JobListing, JobStatus
from job_agent.schemas.packet import ApplicationPacket
from job_agent.validators import validate_profile_bundle


APP_NAME = "Paris Data Career Copilot"
APP_URL_PLACEHOLDER = "https://github.com/m-ihab/free-job-agent"
APP_DESCRIPTION = (
    "A local-first career copilot for data science, AI, and analytics roles in France. "
    "It searches public job data, tracks opportunities, scores fit against my profile, "
    "and prepares tailored CV and cover-letter packets for manual review and submission."
)


def configured_app() -> AppConfig:
    config = AppConfig.load()
    config.ensure_dirs()
    Database(config.db_path).initialize()  # type: ignore[arg-type]
    return config


def is_france_travail_configured() -> bool:
    return bool(os.environ.get("FRANCE_TRAVAIL_CLIENT_ID") and os.environ.get("FRANCE_TRAVAIL_CLIENT_SECRET"))


def latex_compiler() -> str | None:
    for name in ("latexmk", "pdflatex", "xelatex", "lualatex"):
        if shutil.which(name):
            return name
    return None


def profile_status(config: AppConfig | None = None) -> dict[str, Any]:
    config = config or configured_app()
    report = validate_profile_bundle(config)
    compiler = latex_compiler()
    return {
        "valid": not report.errors,
        "errors": report.errors,
        "warnings": report.warnings,
        "profiles_dir": str(config.profiles_dir),
        "data_dir": str(config.data_dir),
        "outputs_dir": str(config.outputs_dir),
        "france_travail_configured": is_france_travail_configured(),
        "latex_compiler": compiler,
        "latex_ready": compiler is not None,
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


def job_to_dict(job: JobListing, latest_packet: ApplicationPacket | None = None) -> dict[str, Any]:
    return {
        "id": job.id,
        "short_id": job.id[:8],
        "title": job.title,
        "company": job.company,
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
    }


def packet_to_dict(packet: ApplicationPacket) -> dict[str, Any]:
    return {
        "id": packet.id,
        "job_id": packet.job_id,
        "status": packet.status.value,
        "fit_score": packet.fit_score,
        "fit_decision": packet.fit_decision,
        "cv_pdf": packet.tailored_cv_pdf_path or "",
        "cover_letter_pdf": packet.cover_letter_pdf_path or "",
        "assistant_page": next((artifact.path for artifact in packet.artifacts if artifact.kind == "assistant_html"), ""),
        "artifacts": [artifact.dict() for artifact in packet.artifacts],
    }


def status_options() -> list[str]:
    return [status.value for status in JobStatus]

