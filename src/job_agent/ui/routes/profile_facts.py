"""Profile-facts editor routes — read/write ``candidate_profile.json``.

These facts drive scoring, work-authorization routing, packet generation, and
screening answers. Writes are validated against the ``CandidateProfile``
schema, preceded by a timestamped backup, and followed by an evidence-store
rebuild so downstream features see the new facts immediately. Everything stays
in the local gitignored profiles directory.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from job_agent.evidence import EvidenceStore
from job_agent.schemas.candidate import CandidateProfile

logger = logging.getLogger(__name__)


def _profile_path(config) -> Path | None:
    if not config.profiles_dir:
        return None
    return Path(config.profiles_dir) / "candidate_profile.json"


def get_profile_facts(h) -> None:
    path = _profile_path(h._config())
    if path is None or not path.exists():
        return h._send_error_json("candidate_profile.json not found — run `job-agent copy-examples` first.", status=404)
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return h._send_error_json(f"candidate_profile.json is not valid JSON: {exc}", status=500)
    h._send_json({"profile": profile, "path": str(path)})


def post_profile_facts(h, payload: dict) -> None:
    config = h._config()
    path = _profile_path(config)
    if path is None or not path.exists():
        return h._send_error_json("candidate_profile.json not found — run `job-agent copy-examples` first.", status=404)
    profile_data = payload.get("profile")
    if not isinstance(profile_data, dict) or not profile_data:
        return h._send_error_json("Request must include a non-empty 'profile' object.")
    try:
        validated = CandidateProfile(**profile_data)
    except Exception as exc:
        return h._send_error_json(f"Profile did not validate: {exc}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"candidate_profile.{stamp}.bak")
    try:
        shutil.copyfile(path, backup)
    except Exception as exc:
        return h._send_error_json(f"Could not write backup before saving: {exc}", status=500)

    path.write_text(
        json.dumps(json.loads(validated.json(exclude_none=True)), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Rebuild the local evidence store so grounded generation and preflight
    # pick up the new facts immediately. Fail-soft: the save itself succeeded.
    evidence_rebuilt = True
    try:
        EvidenceStore.load(config).rebuild(config)
    except Exception:
        evidence_rebuilt = False
        logger.warning("Evidence rebuild after profile save failed", exc_info=True)

    h._send_json({"ok": True, "backup": backup.name, "evidence_rebuilt": evidence_rebuilt})
