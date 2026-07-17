"""Cross-job narrative activity feed from the existing tracker event log."""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from job_agent.db.activity import list_activity_events
from job_agent.ui.route_helpers import _tracker

_SUBSYSTEMS = {"scout", "evaluate", "customize", "apply", "tracker", "system"}
_EVENT_SUBSYSTEM = {
    "JOB_ADDED": "scout",
    "ENRICHED": "scout",
    "COMPANY_RESCAN": "scout",
    "DEDUPED": "scout",
    "FILTER_FAILED": "evaluate",
    "PACKET_SAVED": "customize",
    "PACKET_READY": "customize",
    "COVER_LETTER_ON_DEMAND": "customize",
    "CHROME_SESSION_QUEUED": "apply",
    "ASSISTED_APPLY_OPENED": "apply",
    "MANUALLY_SUBMITTED": "apply",
    "AUTO_SUBMITTED": "apply",
    "NEEDS_MANUAL": "apply",
    "STATUS_CHANGED": "tracker",
    "NOTES_UPDATED": "tracker",
    "JOB_REMOVED": "tracker",
}


def get_activity(h: Any) -> None:
    """Return newest-first real event rows, optionally filtered, capped at 200."""
    subsystem = (
        parse_qs(urlparse(h.path).query).get("subsystem") or [""]
    )[0].strip().casefold()
    if subsystem and subsystem not in _SUBSYSTEMS:
        return h._send_error_json(
            "subsystem must be scout, evaluate, customize, apply, tracker, or system."
        )

    tracker = _tracker(h._config())
    events = [
        _activity_item(event)
        for event in list_activity_events(tracker.db.db_path)
    ]
    events.sort(key=lambda row: (int(row["id"]), str(row["created_at"])), reverse=True)
    if subsystem:
        events = [row for row in events if row["subsystem"] == subsystem]
    h._send_json({"events": events[:200], "subsystem": subsystem or "all"})


def _activity_item(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("event_type") or "UNKNOWN_EVENT").upper()
    raw_data = event.get("event_data")
    data = raw_data if isinstance(raw_data, dict) else {}
    return {
        "id": int(event.get("id") or 0),
        "job_id": str(event.get("job_id") or ""),
        "event_type": event_type,
        "subsystem": _subsystem(event_type),
        "message": _message(
            event_type,
            data,
            str(event.get("job_title") or ""),
            str(event.get("job_company") or ""),
        ),
        "created_at": str(event.get("created_at") or ""),
    }


def _subsystem(event_type: str) -> str:
    if event_type in _EVENT_SUBSYSTEM:
        return _EVENT_SUBSYSTEM[event_type]
    if "APPLY" in event_type or "SUBMIT" in event_type or "MANUAL" in event_type:
        return "apply"
    if "PACKET" in event_type or "LETTER" in event_type:
        return "customize"
    if "FILTER" in event_type or "SCORE" in event_type or "EVALUAT" in event_type:
        return "evaluate"
    return "system"


def _message(event_type: str, data: dict[str, Any], title: str, company: str) -> str:
    label = _job_label(title, company)
    if event_type == "JOB_ADDED":
        return f"Added {label} from {_text(data.get('source'), 'an existing source')}."
    if event_type == "ENRICHED":
        return f"Enriched {label} from {_joined(data.get('sources'), 'stored sources')}."
    if event_type == "COMPANY_RESCAN":
        return f"Updated the company for {title}: {_text(data.get('old'), 'unknown')} to {_text(data.get('new'), company)}."
    if event_type == "DEDUPED":
        return f"Removed duplicate {_text(data.get('removed_id'), 'job')} and kept {label}."
    if event_type == "FILTER_FAILED":
        return f"Preparation failed for {label}: {_joined(data.get('reasons'), 'hard filters failed')}."
    if event_type == "PACKET_SAVED":
        return f"Saved application packet version {_text(data.get('version'), 'unknown')} for {label}."
    if event_type == "PACKET_READY":
        return f"Prepared a {_text(data.get('status'), 'ready')} application packet for {label}."
    if event_type == "COVER_LETTER_ON_DEMAND":
        return f"Generated the requested cover letter for {label}."
    if event_type == "CHROME_SESSION_QUEUED":
        return f"Queued {label} for browser apply."
    if event_type == "ASSISTED_APPLY_OPENED":
        return f"Opened the apply assistant for {label}."
    if event_type == "MANUALLY_SUBMITTED":
        return f"Marked {label} submitted manually."
    if event_type == "AUTO_SUBMITTED":
        return f"Submitted {label} in Full Auto."
    if event_type == "NEEDS_MANUAL":
        return f"Handed {label} to manual apply: {_text(data.get('reason'), 'manual review required')}."
    if event_type == "STATUS_CHANGED":
        status = _text(data.get("new_status") or data.get("status"), "unknown status").replace("_", " ").title()
        note = _text(data.get("note"), "")
        return f"Moved {label} to {status}{f': {note}' if note else ''}."
    if event_type == "NOTES_UPDATED":
        return f"Updated local notes for {label}."
    if event_type == "JOB_REMOVED":
        return f"Removed {label} from the tracker."
    detail = _text(data.get("error") or data.get("reason") or data.get("note"), "")
    name = event_type.replace("_", " ").title()
    return f"Recorded {name} for {label}{f': {detail}' if detail else ''}."


def _text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _job_label(title: str, company: str) -> str:
    if title and company:
        return f"{title} at {company}"
    return title or company or "the local run"


def _joined(value: Any, fallback: str) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item).strip() for item in value if str(item).strip())
        return text or fallback
    return _text(value, fallback)
