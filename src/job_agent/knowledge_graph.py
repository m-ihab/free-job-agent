"""Build the dashboard knowledge graph from local jobs and evidence rows."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from job_agent.db.database import Database
from job_agent.search_quality import assess_search_quality
from job_agent.skill_tokens import is_rome_occupation_code


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", value.casefold()).strip()


def _digest(prefix: str, *values: object) -> str:
    raw = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(raw).hexdigest()[:16]}"


def _seed(node_id: str) -> int:
    return int(hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:8], 16)


def _add_edge(
    edges: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    source: str,
    target: str,
    edge_type: str,
) -> None:
    key = (source, target, edge_type)
    if key not in seen:
        seen.add(key)
        edges.append({"source": source, "target": target, "type": edge_type})


def _evidence_mentions_skill(evidence: dict[str, Any], normalised_skill: str) -> bool:
    label = _normalise(str(evidence.get("label") or ""))
    if label == normalised_skill:
        return True
    if len(normalised_skill) <= 2:
        return False
    haystack = _normalise(f"{evidence.get('label') or ''} {evidence.get('value') or ''}")
    return f" {normalised_skill} " in f" {haystack} "


def _job_node(job: Any) -> dict[str, Any]:
    quality = assess_search_quality(job)
    stored_quality = getattr(job, "search_quality_score", None)
    return {
        "id": f"job:{job.id}",
        "type": "job",
        "label": job.title,
        "meta": {
            "job_id": job.id,
            "company": job.company,
            "status": job.status.value,
            "fit_score": job.fit_score,
            "search_quality_score": stored_quality if stored_quality is not None else quality.get("score"),
            "tech_stack": list(job.tech_stack),
            "stable_seed": _seed(f"job:{job.id}"),
        },
    }


def build_knowledge_graph(db: Database, max_nodes: int = 150) -> dict[str, Any]:
    """Return a capped graph built only from persisted jobs and evidence."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    edge_keys: set[tuple[str, str, str]] = set()
    skills: dict[str, str] = {}

    for job in db.list_jobs(limit=None):
        job_node = _job_node(job)
        nodes[job_node["id"]] = job_node

        company_label = job.company.strip()
        if company_label:
            company_id = _digest("company", _normalise(company_label))
            nodes.setdefault(
                company_id,
                {
                    "id": company_id,
                    "type": "company",
                    "label": company_label,
                    "meta": {"stable_seed": _seed(company_id)},
                },
            )
            _add_edge(edges, edge_keys, job_node["id"], company_id, "at")

        seen_job_skills: set[str] = set()
        for raw_skill in job.tech_stack:
            if is_rome_occupation_code(raw_skill):
                continue
            label = str(raw_skill).strip()
            key = _normalise(label)
            if not key or key in seen_job_skills:
                continue
            seen_job_skills.add(key)
            skill_id = skills.setdefault(key, _digest("skill", key))
            nodes.setdefault(
                skill_id,
                {
                    "id": skill_id,
                    "type": "skill",
                    "label": label,
                    "meta": {"stable_seed": _seed(skill_id)},
                },
            )
            _add_edge(edges, edge_keys, job_node["id"], skill_id, "requires")

    evidence_rows = db.list_evidence_items()
    for item in evidence_rows:
        evidence_id = _digest(
            "evidence",
            item.get("kind"),
            item.get("label"),
            item.get("value"),
            item.get("source"),
            item.get("source_ref"),
        )
        nodes[evidence_id] = {
            "id": evidence_id,
            "type": "evidence",
            "label": str(item.get("label") or item.get("kind") or "Evidence"),
            "meta": {
                "kind": str(item.get("kind") or ""),
                "value": str(item.get("value") or ""),
                "source": str(item.get("source") or ""),
                "source_ref": item.get("source_ref"),
                "confidence": float(item.get("confidence", 1.0)),
                "is_claim": str(item.get("kind") or "").casefold() == "skill",
                "stable_seed": _seed(evidence_id),
            },
        }
        for skill_key, skill_id in skills.items():
            if _evidence_mentions_skill(item, skill_key):
                _add_edge(edges, edge_keys, evidence_id, skill_id, "proves")

    degree = {node_id: 0 for node_id in nodes}
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    for node_id, node in nodes.items():
        node["meta"]["degree"] = degree[node_id]
        node["meta"]["position_source"] = (
            "relations" if degree[node_id] else "stable_seed_no_relations"
        )
        if node["type"] == "skill":
            incoming = [edge for edge in edges if edge["target"] == node_id]
            proof_ids = {edge["source"] for edge in incoming if edge["type"] == "proves"}
            node["meta"]["job_count"] = sum(edge["type"] == "requires" for edge in incoming)
            node["meta"]["evidence_count"] = len(proof_ids)
            node["meta"]["claim_count"] = sum(
                bool(nodes[evidence_id]["meta"].get("is_claim")) for evidence_id in proof_ids
            )

    total_nodes = len(nodes)
    total_edges = len(edges)
    priority = {"job": 0, "skill": 1, "company": 2, "evidence": 3}
    ordered = sorted(
        nodes.values(),
        key=lambda node: (-degree[node["id"]], priority[node["type"]], node["id"]),
    )
    kept_nodes = ordered[: max(0, int(max_nodes))]
    kept_ids = {node["id"] for node in kept_nodes}
    kept_edges = [
        edge for edge in edges if edge["source"] in kept_ids and edge["target"] in kept_ids
    ]
    kept_edges.sort(key=lambda edge: (edge["source"], edge["target"], edge["type"]))
    return {
        "nodes": kept_nodes,
        "edges": kept_edges,
        "truncated": len(kept_nodes) < total_nodes,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
    }
