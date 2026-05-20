"""Profile and packet validation utilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from job_agent.config import AppConfig
from job_agent.schemas.candidate import CandidateProfile, MasterCV, QAProfile

PLACEHOLDER_MARKERS = [
    "edit this",
    "candidate@example.com",
    "candidate data ai paris",
    "candidate-example",
]


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def load_json_model(path: Path, model_cls: type[Any]) -> Any:
    import json
    with path.open(encoding="utf-8") as f:
        return model_cls(**json.load(f))


def load_profile_bundle(config: AppConfig) -> tuple[CandidateProfile, MasterCV, QAProfile]:
    profiles_dir = config.profiles_dir or (config.data_dir / "profiles")
    cp = profiles_dir / "candidate_profile.json"
    cv = profiles_dir / "master_cv.json"
    qa = profiles_dir / "master_qa_profile.json"
    missing = [str(p) for p in [cp, cv, qa] if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing profile files: " + ", ".join(missing))
    return load_json_model(cp, CandidateProfile), load_json_model(cv, MasterCV), load_json_model(qa, QAProfile)


def validate_profile_bundle(config: AppConfig) -> ValidationReport:
    report = ValidationReport(ok=True)
    try:
        profile, master_cv, qa = load_profile_bundle(config)
    except Exception as exc:
        return ValidationReport(ok=False, errors=[str(exc)])

    if not profile.contact.name:
        report.add_error("candidate_profile.contact.name is required")
    if not profile.contact.email:
        report.add_error("candidate_profile.contact.email is required")
    if not profile.target_roles:
        report.add_warning("candidate_profile.target_roles is empty; title scoring will be weak")
    if not profile.skills:
        report.add_warning("candidate_profile.skills is empty; skill scoring will be weak")
    if not master_cv.experience and not master_cv.projects:
        report.add_warning("master_cv has no experience or projects")
    if profile.contact.email != master_cv.contact.email:
        report.add_warning("candidate_profile and master_cv contact emails differ")
    if profile.contact.name != master_cv.contact.name:
        report.add_warning("candidate_profile and master_cv contact names differ")
    if not qa.entries:
        report.add_warning("master_qa_profile has no locked screening answers")
    if profile.salary_min and profile.salary_max and profile.salary_min > profile.salary_max:
        report.add_error("candidate salary_min is greater than salary_max")
    _warn_on_placeholders(report, profile, master_cv, qa)
    return report


def _warn_on_placeholders(report: ValidationReport, profile: CandidateProfile, master_cv: MasterCV, qa: QAProfile) -> None:
    fields = [
        ("candidate_profile.contact.name", profile.contact.name),
        ("candidate_profile.contact.email", profile.contact.email),
        ("candidate_profile.contact.work_authorization", profile.contact.work_authorization or ""),
        ("candidate_profile.summary", profile.summary),
        ("master_cv.contact.name", master_cv.contact.name),
        ("master_cv.contact.email", master_cv.contact.email),
        ("master_cv.summary", master_cv.summary),
    ]
    for index, entry in enumerate(qa.entries[:20], start=1):
        fields.append((f"master_qa_profile.entries[{index}].answer", str(entry.answer)))
        fields.append((f"master_qa_profile.entries[{index}].notes", entry.notes or ""))
    for label, value in fields:
        lowered = value.casefold()
        if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            report.add_warning(f"{label} still looks like example placeholder content")
