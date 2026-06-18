"""POST handlers for AI (chat/summarize/classify/analyze) and Ollama routes."""
from __future__ import annotations

import logging
from http import HTTPStatus

from job_agent.ai_agent import (
    analyze_fit as _ai_analyze_fit,
    chat_about_job as _ai_chat_about_job,
    classify_job as _ai_classify_job,
    summarize_job as _ai_summarize_job,
    suggest_search_queries,
)
from job_agent.db.database import Database
from job_agent.ollama_manage import (
    pull_model as _pull_ollama_model,
    start_ollama_server,
)
from job_agent.polish import PolishOptions, resolve_ollama_model
from job_agent.validators import load_profile_bundle

logger = logging.getLogger(__name__)


def post_ai_chat(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    question = str(payload.get("question") or "").strip()
    history = payload.get("history") or []
    if not job_id or not question:
        return h._send_error_json("job_id and question are required.")
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = db.resolve_job(job_id)
    if not job:
        return h._send_error_json("Job not found.", HTTPStatus.NOT_FOUND)
    profile, master_cv, _ = load_profile_bundle(config)
    reply = _ai_chat_about_job(job, master_cv, profile, question, history if isinstance(history, list) else [])
    if not reply:
        return h._send_error_json(
            "AI chat unavailable. Start Ollama (and make sure a model is pulled) to enable this.",
            HTTPStatus.SERVICE_UNAVAILABLE,
        )
    h._send_json({"reply": reply})


def post_ai_summarize(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        return h._send_error_json("job_id is required.")
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = db.resolve_job(job_id)
    if not job:
        return h._send_error_json("Job not found.", HTTPStatus.NOT_FOUND)
    tldr = _ai_summarize_job(job)
    if not tldr:
        return h._send_error_json("AI summary unavailable.", HTTPStatus.SERVICE_UNAVAILABLE)
    try:
        db.save_ai_cache(job.id, "summary", tldr, resolve_ollama_model())
    except Exception:
        logger.warning("Failed to cache AI summary for job %s", job.id, exc_info=True)
    h._send_json({"summary": tldr})


def post_ai_classify(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        return h._send_error_json("job_id is required.")
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = db.resolve_job(job_id)
    if not job:
        return h._send_error_json("Job not found.", HTTPStatus.NOT_FOUND)
    classification = _ai_classify_job(job)
    if not classification:
        return h._send_error_json("AI classify unavailable.", HTTPStatus.SERVICE_UNAVAILABLE)
    try:
        db.save_ai_cache(job.id, "classify", classification, resolve_ollama_model())
    except Exception:
        logger.warning("Failed to cache AI classification for job %s", job.id, exc_info=True)
    h._send_json({"classification": classification})


def post_ai_analyze(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        return h._send_error_json("job_id is required.")
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    job = db.resolve_job(job_id)
    if not job:
        return h._send_error_json("Job not found.", HTTPStatus.NOT_FOUND)
    profile, master_cv, _ = load_profile_bundle(config)
    analysis = _ai_analyze_fit(job, master_cv, profile, PolishOptions.from_env())
    if analysis is None:
        return h._send_error_json(
            "AI analysis unavailable. Start Ollama and make sure at least one local model is installed.",
            HTTPStatus.SERVICE_UNAVAILABLE,
        )
    h._send_json({"analysis": analysis.to_dict()})


def post_ai_plan_queries(h, payload) -> None:
    config = h._config()
    profile, master_cv, _ = load_profile_bundle(config)
    plan = suggest_search_queries(
        profile,
        master_cv,
        seed_query=str(payload.get("seed_query") or "data scientist"),
        location=str(payload.get("location") or "Paris"),
        language=str(payload.get("language") or "both"),
        internships_only=bool(payload.get("internships_only", True)),
        limit=int(payload.get("limit") or 8),
    )
    h._send_json(plan)


def post_ollama_launch(h, payload) -> None:
    result = start_ollama_server(PolishOptions.from_env())
    h._send_json(result)


def post_ollama_pull(h, payload) -> None:
    model = str(payload.get("model") or "").strip() or "llama3.2:3b"
    h._send_json(_pull_ollama_model(model, PolishOptions.from_env()))
