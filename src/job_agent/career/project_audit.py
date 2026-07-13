"""Deterministic portfolio audit and gap-driven project masterplan."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from job_agent.career.gap_coach import GapCluster
from job_agent.career.project_rules import (
    VERDICT_RULES,
    ProjectVerdict,
    audit_project,
    normalise,
    target_stack,
)
from job_agent.career.project_specs import PROJECT_TEMPLATES, ProjectTemplate
from job_agent.evidence import EvidenceStore
from job_agent.schemas.candidate import CandidateProfile, MasterCV


@dataclass(frozen=True)
class ProjectSpec:
    name: str
    problem: str
    dataset_suggestion: str
    stack: list[str]
    hard_part: str
    deliverable: str
    readme_demo_requirements: list[str]
    time_budget_h: int
    covered_gaps: list[str]
    recruiter_visibility: int
    rank_score: int


@dataclass(frozen=True)
class ProjectAuditReport:
    target_roles: list[str]
    verdict_rules: list[str]
    project_verdicts: list[ProjectVerdict]
    masterplan: list[ProjectSpec]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_project_audit(
    profile: CandidateProfile,
    master_cv: MasterCV,
    evidence_store: EvidenceStore,
    gap_clusters: Iterable[GapCluster],
    *,
    top: int = 5,
) -> ProjectAuditReport:
    """Audit CV projects and generate a gap-ranked portfolio masterplan."""
    if not 4 <= top <= 6:
        raise ValueError("top must be between 4 and 6")
    gaps = list(gap_clusters)
    stack = target_stack(profile.target_roles)
    verdicts = [audit_project(project, stack, evidence_store) for project in master_cv.projects]
    specs = [_build_spec(template, gaps) for template in PROJECT_TEMPLATES]
    specs.sort(
        key=lambda item: (-item.rank_score, -item.recruiter_visibility, item.name.casefold())
    )
    return ProjectAuditReport(
        target_roles=sorted(profile.target_roles, key=str.casefold),
        verdict_rules=list(VERDICT_RULES),
        project_verdicts=verdicts,
        masterplan=specs[:top],
    )


def write_project_audit(report: ProjectAuditReport, path: Path) -> None:
    """Write a deterministic UTF-8 JSON artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _build_spec(template: ProjectTemplate, gaps: list[GapCluster]) -> ProjectSpec:
    covered = sorted(
        {
            gap.name
            for gap in gaps
            if any(_tag_matches_gap(tag, gap.name) for tag in template.gap_tags)
        },
        key=str.casefold,
    )
    return ProjectSpec(
        name=template.name,
        problem=template.problem,
        dataset_suggestion=template.dataset_suggestion,
        stack=list(template.stack),
        hard_part=template.hard_part,
        deliverable=template.deliverable,
        readme_demo_requirements=list(template.readme_demo_requirements),
        time_budget_h=template.time_budget_h,
        covered_gaps=covered,
        recruiter_visibility=template.recruiter_visibility,
        rank_score=len(covered) * template.recruiter_visibility,
    )


def _tag_matches_gap(tag: str, gap: str) -> bool:
    left, right = normalise(tag), normalise(gap)
    return left == right or left in right or right in left
