"""POST handler for the "Why this score" drawer (G2 score-explain).

Thin HTTP shim over :func:`job_agent.scorer.explain_score` — all scoring
logic stays in the scorer (CandidatPro consumes the same JSON shape).
"""

from __future__ import annotations

import logging
from typing import Any

from job_agent import embeddings
from job_agent.feedback import aggregate_feedback, calculate_feedback_adjustment
from job_agent.score_evidence import link_score_evidence
from job_agent.scorer import explain_score
from job_agent.ui.route_helpers import _tracker
from job_agent.validators import load_profile_bundle

logger = logging.getLogger(__name__)


def post_score_explain(h: Any, payload: dict[str, Any]) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        return h._send_error_json("job_id is required.")

    tracker = _tracker(config)
    job = tracker.get_job(job_id)
    if not job:
        return h._send_error_json("Job not found.")

    profile, _master_cv, _qa_profile = load_profile_bundle(config)
    semantic = None
    try:
        semantic = embeddings.semantic_similarity(job, profile, tracker.db)
    except Exception:
        # Fail-soft like the pipeline: the drawer still explains the
        # deterministic components when the local embedding model is absent.
        logger.debug("Semantic similarity skipped in score-explain", exc_info=True)
        semantic = None

    evidence_items: list[dict[str, Any]] = []
    evidence_store_available = True
    try:
        evidence_items = tracker.db.list_evidence_items_with_ids()
    except Exception:
        logger.debug("Evidence store unavailable in score-explain", exc_info=True)
        evidence_store_available = False

    explain = explain_score(job, profile, semantic_score=semantic)
    link_score_evidence(
        explain,
        job,
        evidence_items,
        store_available=evidence_store_available,
    )
    adjustment = calculate_feedback_adjustment(
        job,
        aggregate_feedback(tracker.db.list_feedback()),
        base_score=float(explain["total_score"]),
    )
    explain.update(adjustment.to_dict())
    explain["total_score"] = adjustment.adjusted_score
    h._send_json(
        {
            "explain": explain,
            "job": {"id": job.id, "title": job.title, "company": job.company},
        }
    )
