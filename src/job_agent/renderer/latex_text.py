"""Pure LaTeX text/formatting primitives (split from latex_helpers.py, R1 2026-07-09).

Deterministic string transformations only — no schema knowledge beyond plain
values, no filesystem or compiler access.
"""
from __future__ import annotations

import re
from calendar import month_name


def _escape_latex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _inline_latex(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    escaped = _escape_latex(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\\textit{\1}", escaped)
    return escaped


def _format_date(value: str | None) -> str:
    if not value:
        return "Present"
    match = re.match(r"^(\d{4})-(\d{2})$", value)
    if match:
        year, month = match.groups()
        return f"{month_name[int(month)]} {year}"
    return value


def _date_range(start: str | None, end: str | None) -> str:
    return f"{_format_date(start)} -- {_format_date(end)}"


def _latex_itemize(items: list[str]) -> str:
    if not items:
        return ""
    lines = [r"\begin{itemize}"]
    lines.extend(rf"            \item {_inline_latex(item)}" for item in items)
    lines.append(r"        \end{itemize}")
    return "\n".join(lines)


def _cventry(date: str, title: str, org: str, location: str, details: str) -> str:
    return "\n".join(
        [
            rf"        \cventry{{{_inline_latex(date)}}}{{{_inline_latex(title)}}}{{{_inline_latex(org)}}}{{{_inline_latex(location)}}}{{}}{{",
            details,
            r"        }",
        ]
    )


def _linkedin_handle(url: str | None) -> str:
    if not url:
        return ""
    cleaned = url.rstrip("/")
    if "/in/" in cleaned:
        return cleaned.rsplit("/in/", 1)[1]
    return cleaned.rsplit("/", 1)[-1]


def _github_handle(url: str | None) -> str:
    if not url:
        return ""
    return url.rstrip("/").rsplit("/", 1)[-1]
