"""Read-only GET handlers exposing the local Career Engine."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlparse

from job_agent.career.cert_track import build_cert_plan
from job_agent.career.gap_coach import GapReport, build_gap_report
from job_agent.career.project_audit import build_project_audit
from job_agent.db.database import Database
from job_agent.evidence import EvidenceStore, build_evidence_items
from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.validators import load_profile_bundle

_DEFAULT_THRESHOLD = 70


def get_gap_report(h: Any) -> None:
    """Return aggregate gaps for scored jobs below the requested threshold."""
    try:
        threshold = _threshold_from_path(h.path)
        report, _profile, _master_cv, evidence = _career_context(h, threshold)
        items = evidence.all()
        payload = report.to_dict()
        payload["identity"] = {
            "evidence": sum(item.kind != "skill" for item in items),
            "claimed": sum(item.kind == "skill" for item in items),
        }
        h._send_json(payload)
    except (OSError, ValueError) as exc:
        h._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)


def get_cert_plan(h: Any) -> None:
    """Return the free-first certification plan for current market gaps."""
    try:
        report, _profile, _master_cv, _evidence = _career_context(
            h, _DEFAULT_THRESHOLD
        )
        h._send_json(build_cert_plan(report.clusters, top=5).to_dict())
    except (OSError, ValueError) as exc:
        h._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)


def get_project_plan(h: Any) -> None:
    """Return existing-project verdicts and the gap-ranked masterplan."""
    try:
        report, profile, master_cv, evidence = _career_context(
            h, _DEFAULT_THRESHOLD
        )
        result = build_project_audit(
            profile, master_cv, evidence, report.clusters, top=5
        )
        h._send_json(result.to_dict())
    except (OSError, ValueError) as exc:
        h._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)


def _career_context(
    h: Any, threshold: int
) -> tuple[GapReport, CandidateProfile, MasterCV, EvidenceStore]:
    config = h._config()
    profile, master_cv, qa_profile = load_profile_bundle(config)
    db = Database(config.db_path)
    evidence = EvidenceStore(
        db, build_evidence_items(profile, master_cv, qa_profile)
    )
    report = build_gap_report(db, profile, evidence, threshold=threshold)
    return report, profile, master_cv, evidence


def _threshold_from_path(path: str) -> int:
    raw = (parse_qs(urlparse(path).query).get("threshold") or [str(_DEFAULT_THRESHOLD)])[0]
    try:
        threshold = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("threshold must be an integer between 0 and 100") from exc
    if not 0 <= threshold <= 100:
        raise ValueError("threshold must be between 0 and 100")
    return threshold
