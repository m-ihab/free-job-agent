"""TDD Area 4: Parametrized search quality tests.

Covers _contains_query, _contains_location, and _query_score for the
key matching/rejection rules that keep French data-AI searches clean.
"""
from __future__ import annotations

import pytest

from job_agent.intake.free_apis import (
    _contains_location,
    _contains_query,
    _query_score,
)
from job_agent.schemas.job import JobListing


def _job(title: str = "", location: str = "", description: str = "", remote: bool = False) -> JobListing:
    return JobListing(title=title, company="X", location=location, description=description, remote=remote)


# ── _contains_query: title matching ───────────────────────────────────────────

@pytest.mark.parametrize("query,title,expected", [
    # Direct matches
    ("data scientist", "Data Scientist Paris", True),
    ("machine learning", "Machine Learning Engineer", True),
    ("data analyst", "Data Analyst – Paris CDI", True),
    ("data engineer", "Senior Data Engineer", True),
    # French equivalents via synonym expansion
    ("scientist", "Data Scientifique IA", True),
    ("engineer", "Ingénieur Data", True),
    ("intern", "Stage Data Science", True),
    ("internship", "Stagiaire Machine Learning", True),
    ("alternance", "Alternance Data Analyst", True),
    # Should NOT match — wrong role family
    ("data scientist", "Cancer Registry Abstractor", False),
    ("data scientist", "Product Marketing Manager", False),
    ("machine learning", "Senior Account Executive", False),
    ("data", "Database Administrator", False),   # word-boundary guard
    ("ai", "Main Software Engineer", False),      # word-boundary: "ai" ≠ "main"
    # Empty query always passes
    ("", "Anything At All", True),
    # Stopwords-only query passes
    ("the a an", "Janitor", True),
])
def test_contains_query(query: str, title: str, expected: bool) -> None:
    job = _job(title=title)
    result = _contains_query(job, query)
    assert result is expected, (
        f"_contains_query({query!r}, {title!r}) → {result}, expected {expected}"
    )


# ── _contains_location: Paris / IDF / France aliases ──────────────────────────

@pytest.mark.parametrize("location,job_loc,job_desc,remote,expected", [
    # Paris aliases
    ("paris", "Paris, France", "", False, True),
    ("paris", "75 - Paris 13e Arrondissement", "", False, True),
    ("paris", "Île-de-France", "", False, True),
    ("paris", "IDF", "", False, True),
    ("paris", "Lyon", "Role based in France.", False, True),  # "france" alias covers this
    # IDF covers outer departments
    ("ile-de-france", "92 - Hauts-de-Seine", "", False, True),
    ("ile-de-france", "77 - Seine-et-Marne", "", False, True),
    ("île-de-france", "Paris", "", False, True),
    # France covers major cities
    ("france", "Paris", "", False, True),
    ("france", "Lyon", "", False, True),
    ("france", "Marseille", "", False, True),
    # Remote — only passes when user searches remote/worldwide
    ("remote", "", "", True, True),
    ("worldwide", "", "", True, True),
    # Remote job should NOT pass a Paris location search
    ("paris", "Remote — Worldwide", "", True, False),
    # Empty location always passes
    ("", "Tokyo, Japan", "", False, True),
    # Non-matching locations
    ("paris", "Berlin, Germany", "", False, False),
    ("paris", "New York, NY", "", False, False),
])
def test_contains_location(
    location: str,
    job_loc: str,
    job_desc: str,
    remote: bool,
    expected: bool,
) -> None:
    job = _job(location=job_loc, description=job_desc, remote=remote)
    result = _contains_location(job, location)
    assert result is expected, (
        f"_contains_location({location!r}, job.location={job_loc!r}, remote={remote}) → {result}, expected {expected}"
    )


# ── _query_score: relevance ranking ───────────────────────────────────────────

class TestQueryScore:
    def test_exact_title_match_scores_higher_than_description_match(self) -> None:
        exact_title_job = _job(title="Data Scientist", description="office admin role")
        desc_only_job = _job(title="Office Manager", description="data scientist needed")
        assert _query_score(exact_title_job, "data scientist") > _query_score(desc_only_job, "data scientist")

    def test_empty_query_always_scores_zero(self) -> None:
        job = _job(title="Data Scientist", description="Great role with python")
        assert _query_score(job, "") == 0

    def test_tech_stack_match_boosts_score(self) -> None:
        with_stack = JobListing(title="Data Scientist", company="X", tech_stack=["python", "pandas"])
        without_stack = JobListing(title="Data Scientist", company="X", tech_stack=[])
        assert _query_score(with_stack, "python") >= _query_score(without_stack, "python")

    def test_multi_token_query_scores_higher_on_full_match(self) -> None:
        full_match = _job(title="Machine Learning Engineer")
        partial_match = _job(title="Software Engineer")
        assert _query_score(full_match, "machine learning engineer") > _query_score(partial_match, "machine learning engineer")

    def test_non_matching_job_scores_zero(self) -> None:
        job = _job(title="Sales Manager", description="Grow revenue and manage accounts.")
        assert _query_score(job, "data scientist machine learning") == 0


# ── Edge cases: synonym expansion ─────────────────────────────────────────────

class TestQuerySynonymExpansion:
    def test_scientist_synonym_covers_scientifique(self) -> None:
        """'scientist' query should match French 'scientifique' via synonym expansion."""
        job = _job(title="Data Scientifique IA Paris")
        assert _contains_query(job, "scientist")

    def test_intern_synonym_covers_stage(self) -> None:
        """'intern' query should match French 'stage'."""
        job = _job(title="Stage Data Science Paris")
        assert _contains_query(job, "intern")

    def test_alternance_synonym_covers_apprentissage(self) -> None:
        """'alternance' query should match 'apprentissage'."""
        job = _job(title="Apprentissage Data Analyst")
        assert _contains_query(job, "alternance")

    def test_ai_word_boundary_not_inside_word(self) -> None:
        """'ai' query should NOT match 'main' or 'training'."""
        job_main = _job(title="Main Backend Engineer")
        job_training = _job(title="Training Coordinator")
        assert not _contains_query(job_main, "ai")
        assert not _contains_query(job_training, "ai")

    def test_data_word_boundary_not_inside_database(self) -> None:
        """'data' query should NOT match 'database' in the title."""
        job = _job(title="Database Administrator DBA")
        assert not _contains_query(job, "data")
