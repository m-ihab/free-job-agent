"""Parse local profile exports into verbatim evidence entries."""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from job_agent.evidence import EvidenceItem

_JSON_SECTIONS = ("basics", "work", "education", "skills", "certificates", "languages")
_JSON_ENTRY_SPECS = {
    "work": ("experience", ("position", "name")),
    "education": ("education", ("institution", "studyType", "area")),
    "skills": ("skill", ("name",)),
    "certificates": ("certification", ("name",)),
    "languages": ("language", ("language",)),
}


class ProfileImportError(ValueError):
    """Raised when a local profile export cannot be parsed safely."""


@dataclass(frozen=True)
class ProfileImportResult:
    input_type: str
    entries: list[EvidenceItem]
    section_counts: dict[str, int]
    missing_sections: list[str]


def parse_profile_import(path: Path) -> ProfileImportResult:
    """Auto-detect and parse a JSON Resume or LinkedIn data-export ZIP."""
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise ProfileImportError(f"Profile import file not found: {path}")
    if zipfile.is_zipfile(path):
        from job_agent.intake.profile_import_linkedin import parse_linkedin_export
        return parse_linkedin_export(path)
    if path.suffix.casefold() == ".zip":
        raise ProfileImportError(f"Malformed LinkedIn export ZIP: {path.name}")
    try:
        return parse_json_resume(path)
    except ProfileImportError:
        raise


def parse_json_resume(path: Path) -> ProfileImportResult:
    """Parse JSON Resume data without inferring or rewriting candidate facts."""
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError) as exc:
        raise ProfileImportError(f"Could not read JSON Resume {path.name}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileImportError(
            f"Malformed JSON Resume {path.name} at line {exc.lineno}, column {exc.colno}."
        ) from exc
    if not isinstance(payload, dict):
        raise ProfileImportError(f"Malformed JSON Resume {path.name}: root must be an object.")
    if not any(section in payload for section in _JSON_SECTIONS):
        raise ProfileImportError(f"File {path.name} does not contain recognized JSON Resume sections.")

    entries: list[EvidenceItem] = []
    counts = {section: 0 for section in _JSON_SECTIONS}
    basics = payload.get("basics")
    if basics is not None:
        if not isinstance(basics, dict):
            raise ProfileImportError(f"Malformed JSON Resume {path.name}: basics must be an object.")
        if _has_content(basics):
            entries.append(_json_item("profile", basics, ("name", "label", "email"), path.name, "basics"))
            counts["basics"] = 1

    for section, (kind, label_fields) in _JSON_ENTRY_SPECS.items():
        rows = payload.get(section, [])
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise ProfileImportError(f"Malformed JSON Resume {path.name}: {section} must be an array.")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ProfileImportError(
                    f"Malformed JSON Resume {path.name}: {section}[{index}] must be an object."
                )
            if not _has_content(row):
                continue
            source_ref = f"{section}[{index}]"
            entries.append(_json_item(kind, row, label_fields, path.name, source_ref))
            counts[section] += 1

    missing = [section for section, count in counts.items() if count == 0]
    return ProfileImportResult("json-resume", entries, counts, missing)


def parse_linkedin_export(path: Path) -> ProfileImportResult:
    """Parse a LinkedIn data-export ZIP using its exported CSV files."""
    from job_agent.intake.profile_import_linkedin import parse_linkedin_export as parse_zip
    return parse_zip(Path(path))


def _json_item(
    kind: str,
    payload: dict[str, Any],
    label_fields: tuple[str, ...],
    source: str,
    source_ref: str,
) -> EvidenceItem:
    label = _first_text(payload, label_fields) or source_ref
    value = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return EvidenceItem(kind=kind, label=label, value=value, source=source, source_ref=source_ref)


def _first_text(payload: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = payload.get(field)
        if isinstance(value, str) and value:
            return value
    return ""


def _has_content(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, dict):
        return any(_has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_content(item) for item in value)
    return value is not None
