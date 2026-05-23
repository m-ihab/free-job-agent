"""Tests for the smarter search refinements added in v0.3.

Covers:
- expand_role_family: deterministic data/AI synonym expansion.
- Fingerprint normalization: H/F variants + arrondissement dedupe.
- Contract-aware CV summary closing sentence.
"""
from __future__ import annotations

from job_agent.fingerprint import compute_fingerprint
from job_agent.intake.france_market import ROLE_FAMILY_MAP, expand_role_family
from job_agent.renderer.latex_render import _detect_contract_family, _clean_role_phrase
from job_agent.schemas.job import JobListing


def test_role_family_expansion_for_data_scientist_seed():
    variants = expand_role_family("data scientist")
    assert "data engineer" in variants
    assert "ml engineer" in variants
    assert "ai engineer" in variants


def test_role_family_keys_are_known():
    for key in ["data scientist", "machine learning", "data analyst", "data engineer"]:
        assert key in ROLE_FAMILY_MAP


def test_role_family_passthrough_unknown_seed():
    assert expand_role_family("plumber paris") == ["plumber paris"]


def test_role_family_empty_seed():
    assert expand_role_family("") == []


def test_fingerprint_deduplicates_hf_variants():
    a = JobListing(title="APPRENTISSAGE - Ingénieur ML et Data scientist (F/H)", company="France Travail", location="75 - Paris 1er Arrondissement")
    b = JobListing(title="APPRENTISSAGE - Ingénieur ML et Data scientist (H/F)", company="France Travail", location="75 - Paris 1er Arrondissement")
    assert compute_fingerprint(a) == compute_fingerprint(b)


def test_fingerprint_deduplicates_arrondissement_variants():
    a = JobListing(title="Stage Data Engineer", company="BNP Paribas", location="75 - Paris")
    b = JobListing(title="Stage Data Engineer", company="BNP Paribas", location="75 - Paris 13e Arrondissement")
    assert compute_fingerprint(a) == compute_fingerprint(b)


def test_contract_family_stage():
    job = JobListing(title="Stage Data Engineer - H/F", company="X")
    assert _detect_contract_family(job) == "stage"


def test_contract_family_alternance():
    job = JobListing(title="Alternance Data Scientist", company="X")
    assert _detect_contract_family(job) == "alternance"


def test_contract_family_apprentissage_is_alternance():
    job = JobListing(title="APPRENTISSAGE - Ingénieur ML et Data scientist", company="X")
    assert _detect_contract_family(job) == "alternance"


def test_contract_family_cdi():
    job = JobListing(title="Senior Data Engineer", company="X", description="CDI permanent role")
    assert _detect_contract_family(job) == "cdi"


def test_clean_role_phrase_extracts_known_role():
    assert _clean_role_phrase("APPRENTISSAGE - Ingénieur ML et Data scientist (H/F)") == "Data Scientist"
    assert _clean_role_phrase("Stage Data Engineer - H/F") == "Data Engineer"
    assert _clean_role_phrase("Alternance Data Scientist/ IA Engineer - Paris (F/H)") == "Data Scientist"
