"""Packet auto-tailoring and the optional auto-apply trigger for a cycle.

Collaborators (``load_profile_bundle``, ``generate_packet_for_job``,
``notify_packet_ready``) are reached through the :mod:`job_agent.autopilot`
module object so the autopilot tests' ``monkeypatch.setattr(ap, ...)`` seams
keep working after the split.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import job_agent.autopilot as ap


def build_packets(
    pilot: Any,
    db: Any,
    added: list[str],
    packets: list[str],
    errors: list[str],
) -> tuple[int, int, list[dict[str, Any]]]:
    """Tailor application packets for the highest-fit jobs of this cycle.

    Mutates ``packets`` and ``errors`` in place; returns
    ``(packets_built, ai_skipped, notifications)``.
    """
    packets_built = 0
    ai_skipped = 0
    notifications: list[dict[str, Any]] = []

    # Load the profile bundle once and share it across workers to avoid
    # redundant disk reads per packet.
    shared_profile_bundle = None
    try:
        shared_profile_bundle = ap.load_profile_bundle(pilot.config)
    except Exception as exc:
        errors.append(f"profile_load: {type(exc).__name__}: {exc}")

    # Combine newly-added jobs with pre-existing jobs that have no packet yet.
    catchup_ids = [
        j.id for j in db.list_jobs_without_packets(limit=10)
        if j.id not in added
    ]
    all_job_ids = list(added) + catchup_ids
    candidate_ids = all_job_ids[:pilot.opts.max_packets_per_cycle]

    def _build_one(job_id: str) -> tuple[str, Any, str | None]:
        ai_cache = db.list_ai_cache_for_job(job_id) if db else {}
        ai_fit = (ai_cache or {}).get("fit") or {}
        if ai_fit.get("verdict") == "weak":
            return job_id, None, "ai_skip"
        try:
            pkt = ap.generate_packet_for_job(
                pilot.config, job_id, force=False,
                fast_mode=True,
                profile_bundle=shared_profile_bundle,
            )
            return job_id, pkt, None
        except Exception as exc:
            return job_id, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="pkt") as pool:
        futures = {pool.submit(_build_one, jid): jid for jid in candidate_ids}
        for fut in as_completed(futures):
            jid, pkt, err = fut.result()
            if err == "ai_skip":
                ai_skipped += 1
            elif err:
                errors.append(f"packet/{jid[:8]}: {err}")
            elif pkt is not None:
                if pkt.fit_score is not None and pkt.fit_score >= pilot.opts.auto_packet_threshold:
                    packets.append(pkt.id)
                    packets_built += 1
                    if pilot.opts.email_notify:
                        job_obj = db.resolve_job(jid)
                        if job_obj:
                            notifications.append(
                                ap.notify_packet_ready(pilot.config, job_obj, pkt, reason="Autopilot")
                            )

    return packets_built, ai_skipped, notifications


def maybe_auto_apply(pilot: Any, packets: list[str], errors: list[str]) -> None:
    """If auto-apply is enabled and packets were built, start an apply session."""
    if not (pilot.opts.auto_apply and packets):
        return
    try:
        from job_agent import auto_apply as _aa
        if not _aa.get_state()["running"]:
            _aa.start(
                pilot.config,
                mode=pilot.opts.auto_apply_mode,
                min_score=float(pilot.opts.auto_apply_min_score),
                limit=len(packets),
            )
    except Exception as exc:
        errors.append(f"auto_apply_trigger: {type(exc).__name__}: {exc}")
