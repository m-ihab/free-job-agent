"""GET handler for the evidence-grounded candidate skill tree."""
from __future__ import annotations

from http import HTTPStatus
from typing import Any

from job_agent.db.database import Database
from job_agent.evidence import EvidenceStore, build_evidence_items
from job_agent.skill_tree import build_skill_tree
from job_agent.validators import load_profile_bundle


def get_skill_tree(h: Any) -> None:
    try:
        config = h._config()
        profile, master_cv, qa_profile = load_profile_bundle(config)
        db = Database(config.db_path)
        db.initialize()
        evidence = EvidenceStore(
            db, build_evidence_items(profile, master_cv, qa_profile)
        )
        h._send_json(build_skill_tree(db, profile, master_cv, evidence))
    except (OSError, ValueError) as exc:
        h._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
