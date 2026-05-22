"""Enrichment pipeline for France Travail partner APIs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from job_agent.db.database import Database
from job_agent.config import AppConfig
from job_agent.enrichment_helpers import (
    build_context,
    extract_best_string,
    extract_labels,
    extract_numeric,
    fill_params,
)
from job_agent.intake.france_travail_client import ClientConfig, FranceTravailClient
from job_agent.intake.france_travail_endpoints import load_endpoint_registry
from job_agent.schemas.job import JobListing
from job_agent.scorer import score_job
from job_agent.timeutil import utc_now
from job_agent.tracker import ApplicationTracker
from job_agent.validators import load_profile_bundle


@dataclass
class EnrichOptions:
    rome: bool = True
    anotea: bool = True
    training: bool = True
    labour_market: bool = True
    territory: bool = True
    employer: bool = True
    other: bool = True


def _merge_unique(existing: list[str], additions: list[str]) -> list[str]:
    seen = {item.strip().lower() for item in existing}
    merged = list(existing)
    for item in additions:
        key = item.strip().lower()
        if key and key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def _apply_rome(job: JobListing, report: dict) -> None:
    skills = report.get("rome_skills") or []
    if skills:
        job.tech_stack = _merge_unique(job.tech_stack, skills)
    description = report.get("rome_description")
    if description:
        suffix = f"\n\nROME 4.0: {description}"
        if suffix not in job.description:
            job.description = (job.description or "") + suffix


def _apply_anotea(job: JobListing, report: dict) -> None:
    anotea = report.get("anotea") or {}
    rating = anotea.get("rating")
    if rating is None:
        return
    if rating < 2.5:
        job.risk_flags = sorted(set(job.risk_flags + ["ANOTEA_LOW_RATING"]))
        job.fit_notes.append(f"Anotea rating looks low: {rating}")
    else:
        job.fit_notes.append(f"Anotea rating: {rating}")


def _apply_training(job: JobListing, report: dict) -> None:
    trainings = report.get("training_recommendations") or []
    if trainings:
        job.fit_notes.append("Training suggestions: " + "; ".join(trainings[:5]))


def _apply_labour_market(job: JobListing, report: dict) -> None:
    signals = report.get("labour_market_signals") or []
    if signals:
        job.fit_notes.append("Labour market signals: " + "; ".join(signals[:5]))


def enrich_job(config: AppConfig, job_id: str, options: EnrichOptions | None = None) -> dict:
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    tracker = ApplicationTracker(db)
    job = tracker.get_job(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")

    options = options or EnrichOptions()
    client = FranceTravailClient(ClientConfig())
    registry = load_endpoint_registry()
    context = build_context(job)

    report: dict[str, Any] = {
        "job_id": job.id,
        "company": job.company,
        "title": job.title,
        "updated_at": utc_now(),
        "sources": {},
        "rome_skills": [],
        "rome_contexts": [],
        "rome_crafts": [],
        "rome_description": "",
        "training_recommendations": [],
        "labour_market_signals": [],
        "territory_insights": [],
        "anotea": {},
    }

    def call_endpoint(key: str) -> Any | None:
        spec = registry.get(key)
        if not spec or not spec.enabled or not spec.path:
            report["sources"][key] = "not_configured"
            return None
        params = fill_params(spec.params, context)
        try:
            payload = client.request(key, params=params)
            report["sources"][key] = "ok"
            return payload
        except Exception as exc:
            report["sources"][key] = f"error: {exc}"
            return None

    called_keys: set[str] = set()

    if options.rome:
        skills_payload = call_endpoint("rome_skills")
        report["rome_skills"] = extract_labels(skills_payload)
        called_keys.add("rome_skills")
        contexts_payload = call_endpoint("rome_contexts")
        report["rome_contexts"] = extract_labels(contexts_payload)
        called_keys.add("rome_contexts")
        crafts_payload = call_endpoint("rome_crafts")
        report["rome_crafts"] = extract_labels(crafts_payload)
        called_keys.add("rome_crafts")
        desc_payload = call_endpoint("rome_job_descriptions")
        report["rome_description"] = extract_best_string(desc_payload)
        called_keys.add("rome_job_descriptions")

    if options.employer:
        anotea_payload = call_endpoint("anotea")
        rating = extract_numeric(anotea_payload)
        report["anotea"] = {
            "rating": rating,
            "summary": extract_best_string(anotea_payload),
        }
        called_keys.add("anotea")
        call_endpoint("summary_employer_pages")
        called_keys.add("summary_employer_pages")

    if options.training:
        training_payload = call_endpoint("open_training")
        report["training_recommendations"] = extract_labels(training_payload)
        called_keys.add("open_training")
        call_endpoint("training_leavers")
        called_keys.add("training_leavers")

    if options.labour_market:
        market_payload = call_endpoint("labour_market")
        report["labour_market_signals"] = extract_labels(market_payload)
        called_keys.add("labour_market")
        call_endpoint("access_to_employment")
        called_keys.add("access_to_employment")
        call_endpoint("romeo")
        called_keys.add("romeo")
        call_endpoint("check_offer_jcmo")
        called_keys.add("check_offer_jcmo")
        call_endpoint("right_box")
        called_keys.add("right_box")

    if options.territory:
        territory_payload = call_endpoint("territory_info")
        report["territory_insights"] = extract_labels(territory_payload)
        called_keys.add("territory_info")
        call_endpoint("living_environment")
        called_keys.add("living_environment")
        call_endpoint("agency_repository")
        called_keys.add("agency_repository")
        call_endpoint("my_job_events")
        called_keys.add("my_job_events")

    if options.other:
        for key in registry:
            if key not in called_keys:
                call_endpoint(key)

    _apply_rome(job, report)
    _apply_anotea(job, report)
    _apply_training(job, report)
    _apply_labour_market(job, report)

    try:
        profile, _, _ = load_profile_bundle(config)
    except Exception:
        profile = None
    if profile:
        breakdown = score_job(job, profile)
        job.fit_score = breakdown.total_score
        job.fit_confidence = breakdown.confidence
        job.fit_decision = breakdown.decision
        job.fit_notes = _merge_unique(job.fit_notes, breakdown.notes)
        job.missing_requirements = breakdown.missing_requirements
        job.risk_flags = sorted(set(job.risk_flags + breakdown.risk_flags))

    tracker.db.save_job(job)
    tracker.save_enrichment(job.id, report)
    tracker.db.log_event(job.id, "ENRICHED", {"sources": report["sources"]})
    return report
