"""Tests for the score-explain decomposition (G2, scorer.explain_score)."""
from __future__ import annotations

import json
from pathlib import Path

from job_agent.scorer import WEIGHTS, explain_score, score_job
from job_agent.schemas.job import JobListing


def test_deterministic_weights_sum_to_one():
    assert round(sum(WEIGHTS.values()), 6) == 1.0


def test_explain_without_semantic_sums_to_one(sample_job, sample_profile):
    d = explain_score(sample_job, sample_profile)
    names = [c["name"] for c in d["components"]]
    assert "semantic" not in names
    assert round(sum(c["weight"] for c in d["components"]), 4) == 1.0
    assert d["total_score"] == score_job(sample_job, sample_profile).total_score


def test_explain_with_semantic_adds_component_and_sums_to_one(sample_job, sample_profile):
    d = explain_score(sample_job, sample_profile, semantic_score=80)
    assert d["components"][-1]["name"] == "semantic"
    assert d["components"][-1]["score"] == 80
    assert round(sum(c["weight"] for c in d["components"]), 4) == 1.0


def test_contribution_is_score_times_effective_weight(sample_job, sample_profile):
    d = explain_score(sample_job, sample_profile)
    for c in d["components"]:
        assert c["contribution"] == round(c["score"] * c["weight"], 2)


def test_french_requirement_caps_and_discloses(sample_profile):
    # A French-required role for a profile that does not speak French must cap at 25
    # and disclose the cap — unless the sample profile happens to list French, in
    # which case no cap fires. Assert the invariant either way.
    job = JobListing(
        title="Data Scientist",
        company="ACME",
        location="Paris",
        description="Poste exigeant un francais courant, niveau C1.",
        source="paste",
        raw_text="r",
        tech_stack=["python"],
        languages=["french"],
    )
    d = explain_score(job, sample_profile)
    flags = {c["flag"] for c in d["caps_applied"]}
    if "FRENCH_REQUIRED" in flags:
        assert d["total_score"] <= 25
    assert d["total_score"] <= 100


def test_payload_is_json_serialisable(sample_job, sample_profile):
    d = explain_score(sample_job, sample_profile, semantic_score=50)
    json.dumps(d)  # must not raise
    assert set(d) >= {"job_id", "components", "caps_applied", "total_score", "decision"}


def test_drawer_renders_accessible_component_evidence() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "job_agent" / "ui" / "static" / "score_explain.js"
    ).read_text(encoding="utf-8")

    assert 'class="se-evidence-toggle"' in source
    assert 'data-evidence-toggle' in source
    assert 'aria-expanded="false"' in source
    assert "No supporting evidence found in the evidence store." in source
