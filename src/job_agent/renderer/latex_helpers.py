"""Facade for the LaTeX helper family (R1 split, 2026-07-09).

The original 494-line grab-bag became three cohesive modules:

- :mod:`job_agent.renderer.latex_text` — pure text/format primitives
  (escaping, dates, itemize, cventry, profile handles)
- :mod:`job_agent.renderer.latex_tailor` — job-aware tailoring (keyword
  ranking, contract-family detection, role cleanup, tailored summary)
- :mod:`job_agent.renderer.latex_source_edit` — brace-aware ``\\newcommand``
  surgery on the user's main.tex

This module re-exports every original name so existing imports and test
patch targets keep working (G-3: patch where it's looked up — consumers look
names up HERE or in latex_render, which imports from here).
"""
from __future__ import annotations

from job_agent.renderer.latex_source_edit import (
    _cap_itemize_items,
    _has_command,
    _iter_newcommand_bodies,
    _replace_line_command,
    _replace_newcommand_body,
    _replace_newcommand_branch_bodies,
)
from job_agent.renderer.latex_tailor import (
    _ALTERNANCE_TERMS_RE,
    _CDI_TERMS_RE,
    _FRENCH_HINT_RE,
    _LOCATION_TOKENS_RE,
    _PRIMARY_ROLE_PATTERNS,
    _STAGE_TERMS_RE,
    _clean_role_phrase,
    _contract_aware_tail,
    _detect_contract_family,
    _experience_body,
    _focus_phrase,
    _is_french,
    _job_focus_terms,
    _keyword_score,
    _project_body,
    _rank_texts,
    _skill_score,
    _tailored_summary,
)
from job_agent.renderer.latex_text import (
    _cventry,
    _date_range,
    _escape_latex,
    _format_date,
    _github_handle,
    _inline_latex,
    _latex_itemize,
    _linkedin_handle,
)

__all__ = [
    "_escape_latex", "_inline_latex", "_format_date", "_date_range",
    "_latex_itemize", "_cventry", "_linkedin_handle", "_github_handle",
    "_keyword_score", "_rank_texts", "_experience_body", "_project_body",
    "_skill_score", "_job_focus_terms", "_is_french", "_detect_contract_family",
    "_focus_phrase", "_clean_role_phrase", "_contract_aware_tail",
    "_tailored_summary", "_replace_newcommand_body", "_iter_newcommand_bodies",
    "_replace_newcommand_branch_bodies", "_replace_line_command",
    "_has_command", "_cap_itemize_items",
    "_FRENCH_HINT_RE", "_STAGE_TERMS_RE", "_ALTERNANCE_TERMS_RE",
    "_CDI_TERMS_RE", "_LOCATION_TOKENS_RE", "_PRIMARY_ROLE_PATTERNS",
]
