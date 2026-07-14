"""LinkedIn data-export CSV parsing for local profile ingestion."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path, PurePosixPath

from job_agent.evidence import EvidenceItem
from job_agent.intake.profile_import import ProfileImportError, ProfileImportResult

_CSV_SPECS = {
    "Positions.csv": ("work", "experience", ("Title", "Company Name"), ("Title", "Company Name")),
    "Education.csv": ("education", "education", ("School Name", "Degree Name"), ("School Name",)),
    "Skills.csv": ("skills", "skill", ("Name",), ("Name",)),
    "Certifications.csv": ("certifications", "certification", ("Name",), ("Name",)),
    "Languages.csv": ("languages", "language", ("Name",), ("Name",)),
}


def parse_linkedin_export(path: Path) -> ProfileImportResult:
    """Parse supported CSVs from a LinkedIn archive without changing values."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as archive:
            members = {
                PurePosixPath(info.filename).name.casefold(): info
                for info in archive.infolist()
                if not info.is_dir()
            }
            recognized = [name for name in _CSV_SPECS if name.casefold() in members]
            if not recognized:
                expected = ", ".join(_CSV_SPECS)
                raise ProfileImportError(
                    f"LinkedIn export {path.name} contains none of the expected CSV files: {expected}."
                )
            entries: list[EvidenceItem] = []
            counts = {spec[0]: 0 for spec in _CSV_SPECS.values()}
            for filename, spec in _CSV_SPECS.items():
                info = members.get(filename.casefold())
                if info is None:
                    continue
                section, kind, label_fields, required_fields = spec
                rows = _read_csv(archive.read(info), path.name, filename, required_fields)
                for row_number, row in rows:
                    source_ref = f"{filename}:row[{row_number}]"
                    label = _first_value(row, label_fields) or source_ref
                    value = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                    entries.append(EvidenceItem(kind, label, value, path.name, source_ref))
                    counts[section] += 1
    except ProfileImportError:
        raise
    except (OSError, zipfile.BadZipFile, UnicodeError) as exc:
        raise ProfileImportError(f"Malformed LinkedIn export ZIP {path.name}: {exc}") from exc

    missing = [section for section, count in counts.items() if count == 0]
    return ProfileImportResult("linkedin-export", entries, counts, missing)


def _read_csv(
    data: bytes,
    archive_name: str,
    filename: str,
    required_fields: tuple[str, ...],
) -> list[tuple[int, dict[str, str]]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProfileImportError(f"Malformed {archive_name}/{filename}: expected UTF-8 CSV.") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = tuple(reader.fieldnames or ())
    missing_headers = [field for field in required_fields if field not in headers]
    if missing_headers:
        raise ProfileImportError(
            f"Malformed {archive_name}/{filename}: missing columns {', '.join(missing_headers)}."
        )
    rows: list[tuple[int, dict[str, str]]] = []
    try:
        for row_number, raw in enumerate(reader, start=2):
            if None in raw or any(value is None for value in raw.values()):
                raise ProfileImportError(f"Malformed {archive_name}/{filename} at row {row_number}.")
            row = {str(key): str(value) for key, value in raw.items()}
            if any(value for value in row.values()):
                rows.append((row_number, row))
    except csv.Error as exc:
        raise ProfileImportError(f"Malformed {archive_name}/{filename}: {exc}") from exc
    return rows


def _first_value(row: dict[str, str], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = row.get(field, "")
        if value:
            return value
    return ""
