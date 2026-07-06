"""Story bank + on-demand evaluation API routes for the dashboard."""
from __future__ import annotations

import logging
import uuid

from job_agent import embeddings, story_bank
from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.generator.evaluation import evaluate_job, salary_comparables
from job_agent.validators import load_profile_bundle

logger = logging.getLogger(__name__)

_STORY_TEXT_FIELDS = ("situation", "task", "action", "result", "reflection")


def _db(h) -> tuple[AppConfig, Database]:
    config: AppConfig = h._config()
    db = Database(config.db_path)  # type: ignore[arg-type]
    db.initialize()
    return config, db


def get_stories(h) -> None:
    _, db = _db(h)
    h._send_json({"stories": db.list_stories()})


def post_story_save(h, payload: dict) -> None:
    title = str(payload.get("title") or "").strip()
    if not title:
        return h._send_error_json("title is required.")
    _, db = _db(h)
    story_id = str(payload.get("id") or "").strip() or f"story_{uuid.uuid4().hex[:10]}"
    story = {
        "id": story_id,
        "title": title,
        "skills": [str(s).strip() for s in (payload.get("skills") or []) if str(s).strip()],
        "source": str(payload.get("source") or "manual"),
    }
    for fieldname in _STORY_TEXT_FIELDS:
        story[fieldname] = str(payload.get(fieldname) or "")
    db.save_story(story)
    h._send_json({"ok": True, "id": story_id})


def post_story_delete(h, payload: dict) -> None:
    story_id = str(payload.get("id") or "").strip()
    if not story_id:
        return h._send_error_json("id is required.")
    _, db = _db(h)
    db.delete_story(story_id)
    h._send_json({"ok": True})


def post_story_sync(h, payload: dict) -> None:
    """Seed missing stories from master_cv.json (never overwrites user edits)."""
    config, db = _db(h)
    try:
        _, master_cv, _ = load_profile_bundle(config)
    except Exception as exc:
        return h._send_error_json(f"Profile files not ready: {exc}")
    added = story_bank.sync_story_bank(db, master_cv)
    h._send_json({"ok": True, "added": added, "total": len(db.list_stories())})


def post_evaluate(h, payload: dict) -> None:
    """A-F rubric evaluation for one job, with grounded local salary context."""
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        return h._send_error_json("job_id is required.")
    config, db = _db(h)
    job = db.get_job(job_id)
    if job is None:
        return h._send_error_json("Job not found.", status=404)
    try:
        profile, _, _ = load_profile_bundle(config)
    except Exception as exc:
        return h._send_error_json(f"Profile files not ready: {exc}")
    semantic = None
    try:
        semantic = embeddings.semantic_similarity(job, profile, db)
    except Exception:
        logger.debug("Semantic similarity skipped in evaluate route", exc_info=True)
    evaluation = evaluate_job(job, profile, semantic_score=semantic, config=config)
    h._send_json({
        "evaluation": evaluation.to_dict(),
        "salary_context": salary_comparables(db, job),
    })
