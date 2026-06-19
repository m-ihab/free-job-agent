"""Small fuzzy matching helper with an optional rapidfuzz backend.

The app is designed to run for free and locally. rapidfuzz is preferred when
installed, but this module keeps the core project usable without it.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

_rapidfuzz_fuzz: Any
try:  # pragma: no cover - depends on optional dependency
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
except Exception:  # pragma: no cover - exercised when rapidfuzz is absent
    _rapidfuzz_fuzz = None


def _normalize(value: str) -> str:
    return " ".join((value or "").lower().split())


def ratio(a: str, b: str) -> int:
    """Return an integer 0-100 similarity score."""
    if _rapidfuzz_fuzz is not None:
        return int(_rapidfuzz_fuzz.ratio(a, b))
    a_norm, b_norm = _normalize(a), _normalize(b)
    if not a_norm and not b_norm:
        return 100
    if not a_norm or not b_norm:
        return 0
    return int(round(SequenceMatcher(None, a_norm, b_norm).ratio() * 100))


def partial_ratio(a: str, b: str) -> int:
    """Return a partial-match 0-100 score.

    Fallback implementation is intentionally simple: exact substring matches
    score 100, otherwise use SequenceMatcher over the shorter/longer strings.
    """
    if _rapidfuzz_fuzz is not None:
        return int(_rapidfuzz_fuzz.partial_ratio(a, b))
    a_norm, b_norm = _normalize(a), _normalize(b)
    if not a_norm and not b_norm:
        return 100
    if not a_norm or not b_norm:
        return 0
    short, long = (a_norm, b_norm) if len(a_norm) <= len(b_norm) else (b_norm, a_norm)
    if short in long:
        return 100
    if len(short) <= 3:
        return ratio(short, long)
    best = 0
    window = len(short)
    for i in range(0, max(1, len(long) - window + 1)):
        best = max(best, ratio(short, long[i : i + window]))
    return best


def token_set_ratio(a: str, b: str) -> int:
    if _rapidfuzz_fuzz is not None:
        return int(_rapidfuzz_fuzz.token_set_ratio(a, b))
    a_set = set(_normalize(a).split())
    b_set = set(_normalize(b).split())
    if not a_set and not b_set:
        return 100
    if not a_set or not b_set:
        return 0
    overlap = len(a_set & b_set)
    return int(round(2 * overlap / (len(a_set) + len(b_set)) * 100))
