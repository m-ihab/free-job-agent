"""POST handlers for referral warm-path data."""
from __future__ import annotations

from job_agent.referral import build_referral_ask, get_contact, import_contacts, parse_contacts_payload
from job_agent.ui.route_helpers import _safe_int, _tracker


def post_contacts_import(h, payload) -> None:
    raw_contacts = payload.get("contacts") or []
    if not isinstance(raw_contacts, list):
        return h._send_error_json("contacts must be a list.")
    contacts = parse_contacts_payload([item for item in raw_contacts if isinstance(item, dict)])
    imported = import_contacts(h._config(), contacts)
    h._send_json({"imported": imported})


def post_referral_ask(h, payload) -> None:
    job_id = str(payload.get("job_id") or "").strip()
    contact_id = _safe_int(payload.get("contact_id"), 0, minimum=0, maximum=10_000_000)
    if not job_id or contact_id <= 0:
        return h._send_error_json("job_id and contact_id are required.")
    job = _tracker(h._config()).db.resolve_job(job_id)
    if not job:
        return h._send_error_json("Job not found.")
    contact = get_contact(h._config(), contact_id)
    if not contact:
        return h._send_error_json("Contact not found.")
    h._send_json({"job_id": job.id, "contact": contact.to_dict(), "message": build_referral_ask(h._config(), job, contact)})
