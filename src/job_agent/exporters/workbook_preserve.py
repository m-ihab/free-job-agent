"""Helpers for preserving user-owned columns in generated workbooks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ManualColumnSnapshot:
    """Manual workbook values keyed by a stable job row identity."""

    columns: dict[int, str] = field(default_factory=dict)
    values_by_key: dict[str, dict[int, Any]] = field(default_factory=dict)


def normalise_header(value: object) -> str:
    return str(value or "").strip().casefold()


def sheet_and_header_row(worksheet: Any, exported_columns: list[str]) -> tuple[int, dict[str, int]]:
    expected = {normalise_header(column) for column in exported_columns}
    for row_index in range(1, min(worksheet.max_row, 20) + 1):
        header_map: dict[str, int] = {}
        for cell in worksheet[row_index]:
            label = normalise_header(cell.value)
            if label in expected and label not in header_map:
                header_map[label] = cell.column
        if len(header_map) >= 4:
            return row_index, header_map

    for column_index, column_name in enumerate(exported_columns, start=1):
        worksheet.cell(row=1, column=column_index, value=column_name.title())
    return 1, {normalise_header(name): index for index, name in enumerate(exported_columns, start=1)}


def ensure_headers(
    worksheet: Any,
    *,
    header_row: int,
    header_map: dict[str, int],
    exported_columns: list[str],
) -> dict[str, int]:
    next_column = max([worksheet.max_column, *header_map.values(), 0]) + 1
    for column_name in exported_columns:
        key = normalise_header(column_name)
        if key not in header_map:
            header_map[key] = next_column
            next_column += 1
            worksheet.cell(row=header_row, column=header_map[key], value=column_name.title())
    return header_map


def manual_row_key(company: object, title: object, link: object) -> str:
    """Stable row key: prefer link, else company+title."""
    clean_link = str(link or "").strip().casefold()
    if clean_link:
        return f"link:{clean_link}"
    return f"company-title:{normalise_header(company)}::{normalise_header(title)}"


def snapshot_manual_columns(
    worksheet: Any,
    *,
    header_row: int,
    header_map: dict[str, int],
    exported_columns: list[str],
) -> ManualColumnSnapshot:
    """Capture non-export columns so export can safely rewrite data rows."""
    exported = {normalise_header(name) for name in exported_columns}
    manual_columns: dict[int, str] = {}
    for column in range(1, worksheet.max_column + 1):
        label = str(worksheet.cell(row=header_row, column=column).value or "").strip()
        if label and normalise_header(label) not in exported:
            manual_columns[column] = label
    if not manual_columns:
        return ManualColumnSnapshot()

    company_col = header_map.get("company name")
    title_col = header_map.get("job title")
    link_col = header_map.get("link to job")
    values_by_key: dict[str, dict[int, Any]] = {}
    for row in range(header_row + 1, worksheet.max_row + 1):
        key = manual_row_key(
            worksheet.cell(row=row, column=company_col).value if company_col else "",
            worksheet.cell(row=row, column=title_col).value if title_col else "",
            worksheet.cell(row=row, column=link_col).value if link_col else "",
        )
        values = {
            column: worksheet.cell(row=row, column=column).value
            for column in manual_columns
            if worksheet.cell(row=row, column=column).value not in (None, "")
        }
        if values and key:
            values_by_key[key] = values
    return ManualColumnSnapshot(manual_columns, values_by_key)


def restore_manual_columns(
    worksheet: Any,
    *,
    header_row: int,
    row: int,
    key: str,
    snapshot: ManualColumnSnapshot,
) -> None:
    """Restore preserved values for ``key`` onto ``row``."""
    for column, label in snapshot.columns.items():
        worksheet.cell(row=header_row, column=column, value=label)
    for column, value in snapshot.values_by_key.get(key, {}).items():
        worksheet.cell(row=row, column=column, value=value)
