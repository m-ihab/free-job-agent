"""Tests for headhunter mode — English-first targeting and batch outreach."""
from __future__ import annotations

from job_agent.headhunter import (
    OutreachPack,
    build_batch_outreach,
    build_outreach_pack,
    english_first_strategy_report,
    is_english_first,
    write_batch_outreach_file,
)
from job_agent.schemas.job import JobListing


def _job(**overrides) -> JobListing:
    base = dict(title="Data Scientist", company="ACME")
    base.update(overrides)
    return JobListing(**base)


# --- is_english_first -----------------------------------------------------

def test_is_english_first_matches_known_signal_case_insensitively():
    assert is_english_first("Hugging Face") is True
    assert is_english_first("DATADOG SAS") is True


def test_is_english_first_false_for_unknown_company():
    assert is_english_first("Boulangerie Dupont") is False


# --- build_batch_outreach -------------------------------------------------

def test_build_batch_outreach_filters_below_min_score(sample_master_cv, sample_profile):
    jobs = [
        _job(company="Datadog", fit_score=80),
        _job(company="Datadog", fit_score=40, title="Junior"),
    ]

    packs = build_batch_outreach(jobs, sample_master_cv, sample_profile, min_score=65)

    assert len(packs) == 1
    assert packs[0].score == 80


def test_build_batch_outreach_sorts_by_score_descending(sample_master_cv, sample_profile):
    jobs = [
        _job(company="Datadog", fit_score=70),
        _job(company="Stripe", fit_score=95, title="Senior DS"),
    ]

    packs = build_batch_outreach(jobs, sample_master_cv, sample_profile, min_score=65)

    assert [p.score for p in packs] == [95, 70]


def test_build_batch_outreach_english_first_only_filter(sample_master_cv, sample_profile):
    jobs = [
        _job(company="Datadog", fit_score=80),       # english-first
        _job(company="Local SARL", fit_score=90),    # not english-first
    ]

    packs = build_batch_outreach(
        jobs, sample_master_cv, sample_profile, min_score=65, english_first_only=True
    )

    assert [p.company for p in packs] == ["Datadog"]


# --- build_outreach_pack --------------------------------------------------

def test_build_outreach_pack_populates_all_messages(sample_master_cv, sample_profile):
    pack = build_outreach_pack(
        _job(company="Stripe", fit_score=88), sample_master_cv, sample_profile
    )

    assert isinstance(pack, OutreachPack)
    assert pack.is_english_first is True
    assert pack.connect_request and pack.recruiter_message and pack.outreach_email


def test_outreach_pack_to_markdown_includes_key_sections(sample_master_cv, sample_profile):
    pack = build_outreach_pack(
        _job(company="Stripe", fit_score=88), sample_master_cv, sample_profile
    )

    md = pack.to_markdown()

    assert "Outreach Pack" in md
    assert "LinkedIn Connection Request" in md
    assert "Application Cadence" in md


# --- write_batch_outreach_file -------------------------------------------

def test_write_batch_outreach_file_returns_zero_for_empty(tmp_path):
    out = tmp_path / "batch.md"
    assert write_batch_outreach_file([], out) == 0
    assert not out.exists()


def test_write_batch_outreach_file_writes_all_packs(
    sample_master_cv, sample_profile, tmp_path
):
    packs = build_batch_outreach(
        [_job(company="Datadog", fit_score=80)], sample_master_cv, sample_profile
    )
    out = tmp_path / "batch.md"

    count = write_batch_outreach_file(packs, out)

    assert count == 1
    assert "Batch Outreach Pack" in out.read_text(encoding="utf-8")


# --- english_first_strategy_report ---------------------------------------

def test_strategy_report_separates_english_first_targets():
    jobs = [
        _job(company="Datadog", fit_score=80),
        _job(company="Local SARL", fit_score=90),
    ]

    report = english_first_strategy_report(jobs)

    assert "English-first companies in your tracker**: 1" in report
    assert "Datadog" in report
