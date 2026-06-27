"""POST handlers for application preflight checks."""
from __future__ import annotations

from job_agent.evidence import EvidenceStore
from job_agent.generator.preflight import run_preflight
from job_agent.ui.route_helpers import _latest_packet_for_job, _tracker
from job_agent.validators import load_profile_bundle


def post_preflight(h, payload) -> None:
    config = h._config()
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        return h._send_error_json("job_id is required.")

    tracker = _tracker(config)
    job = tracker.get_job(job_id)
    if not job:
        return h._send_error_json("Job not found.")

    profile, _master_cv, _qa_profile = load_profile_bundle(config)
    evidence = EvidenceStore.load(config)
    if not evidence.all():
        evidence.rebuild(config)

    packet = _latest_packet_for_job(tracker.db, job.id)
    result = run_preflight(job, profile, evidence, config, packet)
    h._send_json({"preflight": result.to_dict()})
