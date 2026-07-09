"""LaTeX source surgery on the user's main.tex (split from latex_helpers.py, R1 2026-07-09).

Brace-aware ``\\newcommand`` body replacement and related string edits.
No schema knowledge, no filesystem access — pure ``str -> str``.
"""
from __future__ import annotations

import re


def _replace_newcommand_body(source: str, command_name: str, body: str) -> str:
    """Replace the body of the first occurrence of ``\\newcommand{\\command_name}``.

    Only the first occurrence is replaced. The user's ``main.tex`` typically
    defines content commands twice — once in the English ``\\ifthenelse``
    branch, once in the French branch — and the French branch should keep its
    curated translation. To update both branches with different bodies, use
    ``_replace_newcommand_branch_bodies``.
    """
    marker = rf"\newcommand{{\{command_name}}}"
    marker_start = source.find(marker)
    if marker_start < 0:
        return source
    body_start = source.find("{", marker_start + len(marker))
    if body_start < 0:
        return source

    depth = 0
    index = body_start
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[: body_start + 1] + "\n" + body.rstrip() + "\n    " + source[index:]
        index += 1
    return source


def _iter_newcommand_bodies(source: str, command_name: str):
    """Yield ``(start, end, body)`` for every occurrence of the named command."""
    pattern_prefix = rf"\newcommand{{\{command_name}}}"
    cursor = 0
    while True:
        marker_start = source.find(pattern_prefix, cursor)
        if marker_start < 0:
            return
        body_start = source.find("{", marker_start + len(pattern_prefix))
        if body_start < 0:
            return
        depth = 0
        index = body_start
        while index < len(source):
            char = source[index]
            if char == "\\":
                index += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    body = source[body_start + 1 : index]
                    yield (body_start + 1, index, body)
                    cursor = index + 1
                    break
            index += 1
        else:
            return


def _replace_newcommand_branch_bodies(source: str, command_name: str, new_bodies: list[str]) -> str:
    """Replace each occurrence of a command with the body at the same index.

    If there are more occurrences than provided bodies, the last body is
    reused. If a body is empty, the original is kept untouched.
    """
    if not new_bodies:
        return source
    positions = list(_iter_newcommand_bodies(source, command_name))
    if not positions:
        return source
    result_parts: list[str] = []
    cursor = 0
    for index, (start, end, _) in enumerate(positions):
        body_index = min(index, len(new_bodies) - 1)
        body = new_bodies[body_index]
        if not body.strip():
            continue
        result_parts.append(source[cursor:start])
        result_parts.append("\n" + body.rstrip() + "\n    ")
        cursor = end
    result_parts.append(source[cursor:])
    return "".join(result_parts)


def _replace_line_command(source: str, pattern: str, replacement: str) -> str:
    return re.sub(pattern, lambda _: replacement, source, count=1, flags=re.MULTILINE)


def _has_command(source: str, command_name: str) -> bool:
    return rf"\newcommand{{\{command_name}}}" in source


def _cap_itemize_items(block: str, max_items: int) -> str:
    """Keep only the first ``max_items`` ``\\item`` entries in one itemize block."""
    segments = block.split(r"\item")
    if len(segments) <= max_items + 1:
        return block
    head = segments[0]
    items = [re.sub(r"\\end\{itemize\}", "", seg) for seg in segments[1:]]
    kept = items[:max_items]
    return head + r"\item" + r"\item".join(kept).rstrip() + "\n        \\end{itemize}"
