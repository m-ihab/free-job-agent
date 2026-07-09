"""POST handler for the "Why this score" drawer (G2 score-explain).

Thin HTTP shim over :func:`job_agent.scorer.explain_score` — all scoring
logic stays in the scorer (CandidatPro consumes the same JSON shape).
"""
from __future__ import annotations

import logging

from job_agent import embeddings
from job_agent.scorer import explain_score
from job_agent.ui.route_helpers import _tracker
from job_agent.validators import load_profile_bundle

logger = logging.getLogger(__name__)


def post_score_explain(h, payload) -> None:
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

    explain = explain_score(job, profile, semantic_score=semantic)
    h._send_json(
        {
            "explain": explain,
            "job": {"id": job.id, "title": job.title, "company": job.company},
        }
    )
