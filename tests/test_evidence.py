"""EvidenceStore population and matching guards."""
from __future__ import annotations

import shutil
from pathlib import Path

from job_agent.config import AppConfig
from job_agent.evidence import EvidenceStore


def _profile_config(tmp_path: Path) -> AppConfig:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    examples = Path("examples")
    for name in ["candidate_profile.json", "master_cv.json", "master_qa_profile.json"]:
        shutil.copyfile(examples / name, profiles / name)
    return AppConfig(
        data_dir=tmp_path / ".job_agent",
        db_path=tmp_path / ".job_agent" / "jobs.db",
        profiles_dir=profiles,
    )


def test_evidence_rebuild_populates_grounded_profile_facts(tmp_path):
    config = _profile_config(tmp_path)
    store = EvidenceStore.load(config)

    store.rebuild(config)
    items = store.all()

    assert any(item.kind == "skill" and item.label == "Python" for item in items)
    assert any(item.kind == "project" and "Classification" in item.label for item in items)
    assert any(item.kind == "education" and "Data Science" in item.value for item in items)
    assert any(item.kind == "screening_answer" and item.source == "master_qa_profile" for item in items)


def test_evidence_for_keyword_matches_fuzzy_terms(tmp_path):
    config = _profile_config(tmp_path)
    store = EvidenceStore.load(config)
    store.rebuild(config)

    labels = {item.label for item in store.for_keyword("scikit learn")}

    assert "scikit-learn" in labels


def test_evidence_supports_rejects_invented_metric(tmp_path):
    config = _profile_config(tmp_path)
    store = EvidenceStore.load(config)
    store.rebuild(config)

    result = store.supports("Reduced cloud costs by 42% with Kubernetes")

    assert result.matched is False
    assert result.confidence == 0


def test_evidence_rebuild_is_idempotent(tmp_path):
    config = _profile_config(tmp_path)
    store = EvidenceStore.load(config)

    store.rebuild(config)
    first = store.all()
    store.rebuild(config)
    second = store.all()

    assert len(second) == len(first)
    assert sorted((item.kind, item.label, item.source_ref or "") for item in second) == sorted(
        (item.kind, item.label, item.source_ref or "") for item in first
    )
