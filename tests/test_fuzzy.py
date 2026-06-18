"""Tests for the fuzzy matcher's pure-Python fallback.

rapidfuzz is preferred when installed, but the project must keep working for
free without it. These tests force the fallback path so that guarantee is
actually exercised (the rapidfuzz branch is covered by normal usage).
"""
from __future__ import annotations

import pytest

from job_agent.utils import fuzzy


@pytest.fixture
def no_rapidfuzz(monkeypatch):
    """Force the pure-Python fallback by disabling the rapidfuzz backend."""
    monkeypatch.setattr(fuzzy, "_rapidfuzz_fuzz", None)


def test_ratio_identical_strings_score_100(no_rapidfuzz):
    assert fuzzy.ratio("data scientist", "Data  Scientist") == 100


def test_ratio_both_empty_is_100(no_rapidfuzz):
    assert fuzzy.ratio("", "") == 100


def test_ratio_one_empty_is_0(no_rapidfuzz):
    assert fuzzy.ratio("python", "") == 0


def test_partial_ratio_substring_scores_100(no_rapidfuzz):
    assert fuzzy.partial_ratio("scientist", "senior data scientist") == 100


def test_partial_ratio_short_string_uses_full_ratio(no_rapidfuzz):
    # len(short) <= 3 falls back to ratio() rather than windowing.
    assert fuzzy.partial_ratio("ml", "machine learning") < 100


def test_partial_ratio_one_empty_is_0(no_rapidfuzz):
    assert fuzzy.partial_ratio("python", "") == 0


def test_token_set_ratio_ignores_word_order(no_rapidfuzz):
    assert fuzzy.token_set_ratio("data scientist", "scientist data") == 100


def test_token_set_ratio_disjoint_tokens_score_0(no_rapidfuzz):
    assert fuzzy.token_set_ratio("python", "rust") == 0


def test_token_set_ratio_partial_overlap_between_0_and_100(no_rapidfuzz):
    score = fuzzy.token_set_ratio("data scientist", "data engineer")
    assert 0 < score < 100


def test_rapidfuzz_backend_returns_int_when_available():
    # When rapidfuzz is present the public API must still return plain ints.
    assert isinstance(fuzzy.ratio("python", "python"), int)
