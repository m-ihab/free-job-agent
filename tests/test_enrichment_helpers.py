"""Tests for enrichment parameter templating and payload parsing helpers.

These recursive parsers feed France Travail enrichment; a regression here
silently drops or mangles enrichment fields.
"""
from __future__ import annotations

from job_agent.enrichment_helpers import (
    build_context,
    extract_best_string,
    extract_department,
    extract_labels,
    extract_numeric,
    extract_siret,
    fill_params,
)
from job_agent.schemas.job import JobListing


def _job(**overrides) -> JobListing:
    base = dict(title="Data Scientist", company="ACME")
    base.update(overrides)
    return JobListing(**base)


# --- extract_department ---------------------------------------------------

def test_extract_department_pulls_numeric_code():
    assert extract_department("Paris 75") == "75"


def test_extract_department_empty_when_no_digits():
    assert extract_department("Paris") == ""
    assert extract_department("") == ""


# --- extract_siret / build_context ---------------------------------------

def test_extract_siret_finds_14_digit_number_in_description():
    job = _job(description="Employer SIRET 12345678901234 hiring now")
    assert extract_siret(job) == "12345678901234"


def test_extract_siret_searches_raw_text_too():
    job = _job(description="", raw_text="ref 98765432109876 end")
    assert extract_siret(job) == "98765432109876"


def test_build_context_derives_siren_from_siret_prefix():
    job = _job(location="Lyon 69", description="SIRET 12345678901234")
    ctx = build_context(job)

    assert ctx["siret"] == "12345678901234"
    assert ctx["siren"] == "123456789"  # first 9 digits
    assert ctx["department"] == "69"
    assert ctx["title"] == "Data Scientist"


# --- fill_params ----------------------------------------------------------

def test_fill_params_substitutes_context_into_string_values():
    out = fill_params({"q": "{company} {title}"}, {"company": "ACME", "title": "DS"})
    assert out == {"q": "ACME DS"}


def test_fill_params_drops_empty_rendered_values():
    out = fill_params({"a": "{department}", "b": "keep"}, {"department": ""})
    assert out == {"b": "keep"}


def test_fill_params_preserves_non_string_values():
    out = fill_params({"limit": 5, "flag": True}, {})
    assert out == {"limit": 5, "flag": True}


def test_fill_params_handles_none_params():
    assert fill_params(None, {"a": "b"}) == {}


# --- extract_labels -------------------------------------------------------

def test_extract_labels_collects_strings_and_dedupes():
    assert extract_labels(["Python", "SQL", "Python"]) == ["Python", "SQL"]


def test_extract_labels_prefers_priority_keys_in_dict():
    payload = [{"libelle": "Data Science", "code": "X"}, {"name": "ML"}]
    assert extract_labels(payload) == ["Data Science", "ML"]


def test_extract_labels_respects_limit():
    payload = [str(i) for i in range(30)]
    assert len(extract_labels(payload, limit=5)) == 5


def test_extract_labels_ignores_none():
    assert extract_labels(None) == []


# --- extract_best_string --------------------------------------------------

def test_extract_best_string_returns_trimmed_string():
    assert extract_best_string("  hello  ") == "hello"


def test_extract_best_string_walks_priority_keys():
    assert extract_best_string({"code": "X", "description": "the desc"}) == "the desc"


def test_extract_best_string_recurses_into_nested_values():
    assert extract_best_string({"outer": {"name": "deep"}}) == "deep"


def test_extract_best_string_empty_for_unmatched_payload():
    assert extract_best_string([{}, 123]) == ""


# --- extract_numeric ------------------------------------------------------

def test_extract_numeric_returns_float_for_number():
    assert extract_numeric(4) == 4.0


def test_extract_numeric_reads_priority_keys():
    assert extract_numeric({"rating": 4.5}) == 4.5


def test_extract_numeric_coerces_comma_decimal_string():
    assert extract_numeric({"note": "3,7"}) == 3.7


def test_extract_numeric_recurses_and_returns_none_when_absent():
    assert extract_numeric([{"label": "x"}, {"deep": {"score": 2}}]) == 2.0
    assert extract_numeric({"label": "x"}) is None
