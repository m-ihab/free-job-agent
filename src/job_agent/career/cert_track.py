"""Deterministic certification planning from Career Engine gap clusters."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from job_agent.career.gap_coach import GapCluster

_CATALOG_PATH = Path(__file__).parents[1] / "data" / "certifications.json"
_STALE_AFTER_DAYS = 90


@dataclass(frozen=True)
class Certification:
    id: str
    name: str
    issuer: str
    cost: str
    est_hours: float
    skill_tags: list[str]
    recruiter_weight: int
    roles_it_moves: list[str]
    checked_date: date


@dataclass(frozen=True)
class CertificationRecommendation:
    certification: Certification
    signal_per_hour: float
    matched_gaps: list[str]
    gap_coverage: int


@dataclass(frozen=True)
class CertPlan:
    as_of: date
    gap_count: int
    recommendations: list[CertificationRecommendation]
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return _json_ready(asdict(self))


def load_certification_catalog(path: Path | None = None) -> list[Certification]:
    """Load and validate the checked-in free-first certification catalog."""
    raw = json.loads((path or _CATALOG_PATH).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("certification catalog must be a JSON list")
    catalog = [_parse_certification(row) for row in raw]
    ids = [item.id for item in catalog]
    if len(ids) != len(set(ids)):
        raise ValueError("certification catalog ids must be unique")
    return catalog


def build_cert_plan(
    gap_clusters: Iterable[GapCluster],
    *,
    catalog: list[Certification] | None = None,
    top: int = 5,
    as_of: date | None = None,
) -> CertPlan:
    """Rank matching certifications by signal/hour, then by gap coverage."""
    if not 3 <= top <= 5:
        raise ValueError("top must be between 3 and 5")
    gaps = list(gap_clusters)
    items = load_certification_catalog() if catalog is None else list(catalog)
    today = as_of or date.today()
    recommendations: list[CertificationRecommendation] = []
    for cert in items:
        matched = sorted(
            (gap.name for gap in gaps if _cert_matches_gap(cert, gap)),
            key=str.casefold,
        )
        if not matched:
            continue
        recommendations.append(
            CertificationRecommendation(
                certification=cert,
                signal_per_hour=round(cert.recruiter_weight / cert.est_hours, 4),
                matched_gaps=matched,
                gap_coverage=len(matched),
            )
        )
    recommendations.sort(
        key=lambda item: (
            -item.signal_per_hour,
            -item.gap_coverage,
            item.certification.name.casefold(),
        )
    )
    warnings = [
        f"Catalog entry {cert.id} is stale: checked {cert.checked_date.isoformat()} "
        f"({(today - cert.checked_date).days} days ago)."
        for cert in items
        if (today - cert.checked_date).days > _STALE_AFTER_DAYS
    ]
    return CertPlan(today, len(gaps), recommendations[:top], warnings)


def write_cert_plan(plan: CertPlan, path: Path) -> None:
    """Write a deterministic UTF-8 JSON artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(plan.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _parse_certification(row: object) -> Certification:
    if not isinstance(row, dict):
        raise ValueError("each certification entry must be an object")
    cert = Certification(
        id=str(row["id"]),
        name=str(row["name"]),
        issuer=str(row["issuer"]),
        cost=str(row["cost"]),
        est_hours=float(row["est_hours"]),
        skill_tags=[str(item) for item in row["skill_tags"]],
        recruiter_weight=int(row["recruiter_weight"]),
        roles_it_moves=[str(item) for item in row["roles_it_moves"]],
        checked_date=date.fromisoformat(str(row["checked_date"])),
    )
    if cert.est_hours <= 0 or not 1 <= cert.recruiter_weight <= 3:
        raise ValueError(f"invalid hours or recruiter weight for {cert.id}")
    if not cert.skill_tags or not cert.roles_it_moves:
        raise ValueError(f"skill_tags and roles_it_moves are required for {cert.id}")
    return cert


def _cert_matches_gap(cert: Certification, gap: GapCluster) -> bool:
    gap_text = _normalise(" ".join([gap.name, *(item.component for item in gap.evidence)]))
    return any(
        (tag := _normalise(skill_tag)) and (tag in gap_text or gap_text in tag)
        for skill_tag in cert.skill_tags
    )


def _normalise(value: str) -> str:
    return " ".join(value.casefold().replace("/", " ").replace("-", " ").split())


def _json_ready(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    value["as_of"] = value["as_of"].isoformat()  # type: ignore[union-attr]
    for row in value["recommendations"]:  # type: ignore[union-attr]
        row["certification"]["checked_date"] = row["certification"]["checked_date"].isoformat()
    return value
