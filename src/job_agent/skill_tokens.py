"""Shared honesty checks for values presented as career skills."""

from __future__ import annotations

import re


_ROME_OCCUPATION_CODE = re.compile(r"[A-N][0-9]{4}", re.IGNORECASE)


def is_rome_occupation_code(value: object) -> bool:
    """Return whether ``value`` is a French ROME occupation code, not a skill.

    ROME identifiers such as ``M1905`` classify occupations in France.  They can
    remain in source text for traceability, but career surfaces must not present
    them as technologies, learning gaps, certifications, or skill nodes.
    """
    return bool(_ROME_OCCUPATION_CODE.fullmatch(str(value).strip()))
