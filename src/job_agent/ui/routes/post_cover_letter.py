"""POST handler for on-demand cover-letter generation."""
from __future__ import annotations

from job_agent.cover_letter_gate import generate_cover_letter_on_demand
from job_agent.ui.services import packet_to_dict


def post_cover_letter(h, payload) -> None:
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        return h._send_error_json("job_id is required.")
    try:
        packet = generate_cover_letter_on_demand(h._config(), job_id)
    except ValueError as exc:
        return h._send_error_json(str(exc))
    h._send_json({"packet": packet_to_dict(packet)})
