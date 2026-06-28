"""GET handlers for referral warm-path data."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from job_agent.referral import list_contacts, match_warm_paths
from job_agent.ui.route_helpers import _safe_int, _tracker


def get_contacts(h) -> None:
    h._send_json({"contacts": [contact.to_dict() for contact in list_contacts(h._config())]})


def get_referrals(h) -> None:
    parsed = urlparse(h.path)
    query = parse_qs(parsed.query)
    job_id = (query.get("job_id") or [""])[0]
    limit = _safe_int((query.get("limit") or ["5"])[0], 5, minimum=1, maximum=20)
    if not job_id:
        return h._send_error_json("job_id is required.")
    job = _tracker(h._config()).db.resolve_job(job_id)
    if not job:
        return h._send_error_json("Job not found.")
    matches = match_warm_paths(h._config(), job, limit=limit)
    h._send_json({"job_id": job.id, "matches": [match.to_dict() for match in matches]})
