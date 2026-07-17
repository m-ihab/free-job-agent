"""Evidence-grounded skill tree assembled from the existing Career engines."""
from __future__ import annotations

import re
from typing import Any

from job_agent.career.cert_track import build_cert_plan
from job_agent.career.gap_coach import GapCluster, build_gap_report
from job_agent.career.project_audit import build_project_audit
from job_agent.db.database import Database
from job_agent.evidence import EvidenceStore
from job_agent.knowledge_graph import _digest
from job_agent.schemas.candidate import CandidateProfile, MasterCV
from job_agent.schemas.job import JobListing
from job_agent.skill_extractor import _IMPLICATION_MAP
from job_agent.skill_tree_roles import build_role_payloads
from job_agent.skill_tokens import is_rome_occupation_code

_GAP_PREFIXES = ("skill:", "ats_gap:")


def build_skill_tree(
    db: Database,
    profile: CandidateProfile,
    master_cv: MasterCV,
    evidence_store: EvidenceStore,
) -> dict[str, list[dict[str, Any]]]:
    """Return claim, proof, and low-score-gap nodes without synthesizing data."""
    jobs = db.list_jobs(limit=None)
    report = build_gap_report(db, profile, evidence_store)
    cert_plan = build_cert_plan(report.clusters, top=5)
    project_plan = build_project_audit(profile, master_cv, evidence_store, report.clusters, top=5)

    labels: dict[str, str] = {}
    claim_keys = _claim_labels(profile, master_cv, labels)
    _evidence_skill_labels(master_cv, labels)
    required_by = _required_by_job(jobs, labels)
    gap_rows = _gap_rows(report.clusters, labels)

    evidence_counts: dict[str, int] = {}
    claim_counts: dict[str, int] = {}
    for key, label in labels.items():
        matches = evidence_store.for_keyword(label)
        evidence_counts[key] = len({item for item in matches if item.kind != "skill"})
        claim_counts[key] = sum(item.kind == "skill" and _normalise(item.label) == key for item in evidence_store.all())

    included = {
        key
        for key in labels
        if evidence_counts[key] or key in claim_keys or key in gap_rows
    }
    ids = {key: _digest("skill", key) for key in included}
    skills = [
        _skill_payload(
            key,
            labels[key],
            ids,
            evidence_counts,
            claim_counts,
            gap_rows,
            required_by,
            cert_plan.recommendations,
            project_plan.masterplan,
            report.clusters,
        )
        for key in sorted(included, key=lambda item: labels[item].casefold())
    ]
    roles = build_role_payloads(profile.target_roles, jobs, labels, ids, evidence_counts)
    return {"skills": skills, "roles": roles}


def _claim_labels(profile: CandidateProfile, master_cv: MasterCV, labels: dict[str, str]) -> set[str]:
    claims: set[str] = set()
    for skill in [*profile.skills, *master_cv.skills]:
        key = _remember(labels, skill.name)
        if key:
            claims.add(key)
    return claims


def _evidence_skill_labels(master_cv: MasterCV, labels: dict[str, str]) -> None:
    for experience in master_cv.experience:
        for skill in experience.technologies:
            _remember(labels, skill)
    for project in master_cv.projects:
        for skill in project.technologies:
            _remember(labels, skill)


def _gap_rows(
    clusters: list[GapCluster], labels: dict[str, str]
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for cluster in clusters:
        for receipt in cluster.evidence:
            prefix = next(
                (item for item in _GAP_PREFIXES if receipt.component.startswith(item)),
                None,
            )
            if prefix is None:
                continue
            label = receipt.component[len(prefix) :].strip()
            key = _remember(labels, label)
            if not key:
                continue
            row = rows.setdefault(key, {"clusters": set(), "jobs": set()})
            row["clusters"].add(cluster.name)
            row["jobs"].add(receipt.job_id)
    return rows


def _required_by_job(jobs: list[JobListing], labels: dict[str, str]) -> dict[str, set[str]]:
    required: dict[str, set[str]] = {}
    for job in jobs:
        for raw_skill in job.tech_stack:
            if is_rome_occupation_code(raw_skill):
                continue
            key = _remember(labels, raw_skill)
            if key:
                required.setdefault(key, set()).add(job.id)
    return required


def _skill_payload(
    key: str,
    label: str,
    ids: dict[str, str],
    evidence_counts: dict[str, int],
    claim_counts: dict[str, int],
    gap_rows: dict[str, dict[str, Any]],
    required_by: dict[str, set[str]],
    certs: list[Any],
    projects: list[Any],
    clusters: list[GapCluster],
) -> dict[str, Any]:
    gap = gap_rows.get(key, {"clusters": set(), "jobs": set()})
    cluster_names = set(gap["clusters"])
    state = "unlocked" if evidence_counts[key] else "claimed" if claim_counts[key] else "locked"
    relevant_certs = [
        {
            "name": row.certification.name,
            "issuer": row.certification.issuer,
            "cost": row.certification.cost,
            "estHours": row.certification.est_hours,
        }
        for row in certs
        if cluster_names.intersection(row.matched_gaps)
    ][:3]
    relevant_projects = [
        {
            "name": row.name,
            "hardPart": row.hard_part,
            "deliverable": row.deliverable,
            "timeBudgetHours": row.time_budget_h,
        }
        for row in projects
        if cluster_names.intersection(row.covered_gaps)
    ][:3]
    payload: dict[str, Any] = {
        "id": ids[key],
        "label": label,
        "state": state,
        "evidenceCount": evidence_counts[key],
        "claimCount": claim_counts[key],
        "jobsRequiring": len(required_by.get(key, set())),
        "parents": _parents_for(key, ids),
        "unlock": {
            "certs": relevant_certs,
            "projects": relevant_projects,
            "jobsBlocked": len(gap["jobs"]),
        },
    }
    lifts = [
        cluster.simulated_score_lift.average_points
        for cluster in clusters
        if cluster.name in cluster_names
    ]
    if cluster_names:
        payload["scoreLift"] = round(max(lifts, default=0.0), 2)
    return payload


def _parents_for(key: str, ids: dict[str, str]) -> list[str]:
    parents = {
        ids[parent_key]
        for parent, children in _IMPLICATION_MAP.items()
        if (parent_key := _normalise(parent)) in ids
        and any(_normalise(child) == key for child in children)
    }
    return sorted(parents)


def _remember(labels: dict[str, str], label: str) -> str:
    key = _normalise(label)
    if key:
        labels.setdefault(key, str(label).strip())
    return key


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", str(value).casefold()).strip()
