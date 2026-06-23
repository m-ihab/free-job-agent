"""POST handlers for search, intake, packet generation and enrichment routes."""
from __future__ import annotations

from http import HTTPStatus
from pathlib import Path

from job_agent.cv_template import import_cv_template_upload
from job_agent.db.database import Database
from job_agent.enrichment import EnrichOptions, enrich_job
from job_agent.intake.bulk_add import bulk_add_jobs
from job_agent.pipeline import add_text_job, add_url_job, generate_packet_for_job
from job_agent.profile_enrich import enrich_from_github, enrich_from_linkedin_skills
from job_agent.tracker_file import import_tracker
from job_agent.utils.net import UnsafeUrlError
from job_agent.ui.route_helpers import (
    _api_search,
    _enrich_batch,
    _export_internships,
    _latest_packet_for_job,
    _multi_source_search,
    _one_click_hunt,
    _resolve_github_handle,
    _search_links,
)
from job_agent.ui.services import job_to_dict, packet_to_dict


def post_search_links(h, payload) -> None:
    h._send_json(_search_links(payload))


def post_api_search(h, payload) -> None:
    h._send_json(_api_search(h._config(), payload))


def post_multi_search(h, payload) -> None:
    h._send_json(_multi_source_search(h._config(), payload))


def post_one_click_hunt(h, payload) -> None:
    h._send_json(_one_click_hunt(h._config(), payload))


def post_add_url(h, payload) -> None:
    config = h._config()
    url = str(payload.get("url") or "").strip()
    if not url:
        return h._send_error_json("URL is required.")
    try:
        job, created = add_url_job(config, url)
    except UnsafeUrlError as exc:
        return h._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    packet = _latest_packet_for_job(db, job.id)
    h._send_json({"created": created, "job": job_to_dict(job, packet)})


def post_add_text(h, payload) -> None:
    config = h._config()
    text = str(payload.get("text") or "").strip()
    if not text:
        return h._send_error_json("Job text is required.")
    job, created = add_text_job(
        config,
        text,
        title=str(payload.get("title") or "") or None,
        company=str(payload.get("company") or "") or None,
        url=str(payload.get("url") or "") or None,
    )
    h._send_json({"created": created, "job": job_to_dict(job)})


def post_add_bulk(h, payload) -> None:
    config = h._config()
    text = str(payload.get("text") or "").strip()
    raw_urls = payload.get("urls") or []
    urls = [str(u) for u in raw_urls] if isinstance(raw_urls, list) else []
    if not text and not urls:
        return h._send_error_json(
            "Paste one or more job posts (separated by '---' or a blank line) or URLs."
        )
    result = bulk_add_jobs(config, text=text, urls=urls)
    h._send_json(result)


def post_generate_packet(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        return h._send_error_json("job_id is required.")
    packet = generate_packet_for_job(config, job_id, force=bool(payload.get("force", False)))
    h._send_json({"packet": packet_to_dict(packet)})


def post_enrich(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        return h._send_error_json("job_id is required.")
    options = EnrichOptions(
        rome=bool(payload.get("rome", True)),
        anotea=bool(payload.get("anotea", True)),
        training=bool(payload.get("training", True)),
        labour_market=bool(payload.get("labour_market", True)),
        territory=bool(payload.get("territory", True)),
        employer=bool(payload.get("employer", True)),
        other=bool(payload.get("other", True)),
    )
    report = enrich_job(config, job_id, options)
    h._send_json({"report": report})


def post_enrich_batch(h, payload) -> None:
    h._send_json(_enrich_batch(h._config(), payload))


def post_enrich_github(h, payload) -> None:
    config = h._config()
    handle = _resolve_github_handle(config, payload)
    if not handle:
        return h._send_error_json("GitHub handle is required. Set contact.github_url in candidate_profile.json or pass 'handle'.")
    report = enrich_from_github(Path(config.profiles_dir), handle, add_projects=bool(payload.get("add_projects", True)))
    h._send_json({"report": report})


def post_enrich_linkedin(h, payload) -> None:
    config = h._config()
    text = str(payload.get("text") or "")
    report = enrich_from_linkedin_skills(Path(config.profiles_dir), text)
    h._send_json({"report": report})


def post_export_internships(h, payload) -> None:
    h._send_json(_export_internships(h._config(), payload))


def post_tracker_import(h, payload) -> None:
    """Sync status edits from the internship tracking workbook back into the DB."""
    h._send_json(import_tracker(h._config()))


def post_import_cv_template(h, payload) -> None:
    config = h._config()
    filename = str(payload.get("filename") or "").strip()
    content = str(payload.get("content_base64") or "").strip()
    if not filename or not content:
        return h._send_error_json("filename and content_base64 are required.")
    h._send_json(import_cv_template_upload(config, filename=filename, content_base64=content))
