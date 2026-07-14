"""Tests for local semantic embeddings (Ollama /api/embed) and scorer blend."""
from __future__ import annotations

from pathlib import Path

import pytest

from job_agent import embeddings as emb
from job_agent.db.database import Database
from job_agent.schemas.candidate import CandidateProfile, ContactInfo, Skill
from job_agent.schemas.job import JobListing
from job_agent.scorer import score_job


def _job(**kwargs) -> JobListing:
    base: dict = dict(
        title="Data Scientist",
        company="Acme",
        description="Machine learning role with Python and SQL.",
        tech_stack=["python", "sql"],
    )
    base.update(kwargs)
    return JobListing(**base)


def _profile(**kwargs) -> CandidateProfile:
    base: dict = dict(
        contact=ContactInfo(name="Test Candidate", email="test@example.com"),
        skills=[Skill(name="Python"), Skill(name="SQL")],
        target_roles=["Data Scientist"],
        target_locations=["Paris"],
        languages=["English", "French"],
    )
    base.update(kwargs)
    return CandidateProfile(**base)


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


# ---- cosine similarity ----

def test_cosine_identical_vectors_is_one() -> None:
    assert emb.cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors_is_zero() -> None:
    assert emb.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_empty_or_mismatched_is_zero() -> None:
    assert emb.cosine_similarity([], []) == 0.0
    assert emb.cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert emb.cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


# ---- model resolution ----

def test_resolve_embed_model_prefers_embedding_family() -> None:
    installed = ["llama3.2:3b", "nomic-embed-text:latest", "qwen3:latest"]
    options = emb.EmbeddingOptions()
    assert emb.resolve_embed_model(options, installed=installed) == "nomic-embed-text:latest"


def test_resolve_embed_model_none_when_only_chat_models() -> None:
    installed = ["llama3.2:3b", "qwen3:latest", "mistral:latest"]
    options = emb.EmbeddingOptions()
    assert emb.resolve_embed_model(options, installed=installed) is None


def test_resolve_embed_model_explicit_override_when_installed() -> None:
    installed = ["bge-m3:latest", "nomic-embed-text:latest"]
    options = emb.EmbeddingOptions(model="bge-m3:latest")
    assert emb.resolve_embed_model(options, installed=installed) == "bge-m3:latest"


def test_resolve_embed_model_disabled_returns_none() -> None:
    installed = ["nomic-embed-text:latest"]
    options = emb.EmbeddingOptions(disabled=True)
    assert emb.resolve_embed_model(options, installed=installed) is None


def test_resolve_embed_model_no_models_returns_none() -> None:
    options = emb.EmbeddingOptions()
    assert emb.resolve_embed_model(options, installed=[]) is None


# ---- HTTP embed client ----

class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeRequests:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def post(self, url: str, json: dict, timeout: int) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse(self.payload)


def test_embed_text_parses_embed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRequests({"embeddings": [[0.1, 0.2, 0.3]]})
    monkeypatch.setattr(emb, "requests", fake)
    vector = emb.embed_text("hello", model="nomic-embed-text:latest")
    assert vector == [0.1, 0.2, 0.3]
    assert fake.calls[0]["url"].endswith("/api/embed")
    assert fake.calls[0]["json"]["model"] == "nomic-embed-text:latest"


def test_embed_text_returns_none_on_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        def post(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(emb, "requests", _Boom())
    assert emb.embed_text("hello", model="nomic-embed-text:latest") is None


def test_embed_text_returns_none_on_malformed_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRequests({"unexpected": True})
    monkeypatch.setattr(emb, "requests", fake)
    assert emb.embed_text("hello", model="nomic-embed-text:latest") is None


def test_embed_text_returns_none_without_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emb, "requests", None)
    assert emb.embed_text("hello", model="nomic-embed-text:latest") is None


# ---- cached job/profile embeddings ----

def _counting_embedder(vector: list[float]):
    calls = {"count": 0}

    def _embed(text: str, model: str) -> list[float]:
        calls["count"] += 1
        return list(vector)

    return _embed, calls


def test_job_embedding_cached_after_first_call(db: Database) -> None:
    job = _job()
    embedder, calls = _counting_embedder([0.5, 0.5])
    first = emb.get_job_embedding(db, job, model="m", embedder=embedder)
    second = emb.get_job_embedding(db, job, model="m", embedder=embedder)
    assert first == [0.5, 0.5]
    assert second == [0.5, 0.5]
    assert calls["count"] == 1


def test_job_embedding_reembeds_when_text_changes(db: Database) -> None:
    job = _job()
    embedder, calls = _counting_embedder([0.5, 0.5])
    emb.get_job_embedding(db, job, model="m", embedder=embedder)
    job.description = "Totally different description about data engineering."
    emb.get_job_embedding(db, job, model="m", embedder=embedder)
    assert calls["count"] == 2


def test_profile_embedding_cached(db: Database) -> None:
    profile = _profile()
    embedder, calls = _counting_embedder([1.0, 0.0])
    first = emb.get_profile_embedding(db, profile, model="m", embedder=embedder)
    second = emb.get_profile_embedding(db, profile, model="m", embedder=embedder)
    assert first == [1.0, 0.0]
    assert second == [1.0, 0.0]
    assert calls["count"] == 1


def test_embedding_failure_returns_none_and_does_not_cache(db: Database) -> None:
    job = _job()

    def _failing(text: str, model: str) -> None:
        return None

    assert emb.get_job_embedding(db, job, model="m", embedder=_failing) is None
    assert db.get_embedding(job.id, "job") is None


# ---- semantic similarity ----

def test_semantic_similarity_identical_vectors_scores_100(db: Database) -> None:
    embedder, _ = _counting_embedder([0.3, 0.7])
    score = emb.semantic_similarity(_job(), _profile(), db, model="m", embedder=embedder)
    assert score == 100


def test_semantic_similarity_none_when_model_unavailable(db: Database) -> None:
    options = emb.EmbeddingOptions(disabled=True)
    score = emb.semantic_similarity(_job(), _profile(), db, options=options)
    assert score is None


def test_semantic_similarity_uses_onnx_after_ollama(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emb, "resolve_embed_model", lambda options=None, installed=None: None)
    monkeypatch.setattr(emb.onnx_embeddings, "is_available", lambda: True)
    monkeypatch.setattr(
        emb.onnx_embeddings, "embed_texts", lambda texts: [[0.6, 0.8] for _ in texts]
    )

    assert emb.semantic_similarity(_job(), _profile(), db, options=emb.EmbeddingOptions()) == 100


def test_semantic_similarity_does_not_use_hashing_by_default(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emb, "resolve_embed_model", lambda options=None, installed=None: None)
    monkeypatch.setattr(emb.onnx_embeddings, "is_available", lambda: False)

    assert emb.semantic_similarity(_job(), _profile(), db, options=emb.EmbeddingOptions()) is None


def test_semantic_similarity_hashing_requires_explicit_opt_in(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emb, "resolve_embed_model", lambda options=None, installed=None: None)
    monkeypatch.setattr(emb.onnx_embeddings, "is_available", lambda: False)
    monkeypatch.setattr(emb.hash_embeddings, "embed_text", lambda text: [0.6, 0.8])
    options = emb.EmbeddingOptions(allow_hash_similarity=True)

    assert emb.semantic_similarity(_job(), _profile(), db, options=options) == 100


# ---- near-duplicate detection ----

def test_find_near_duplicate_same_company_above_threshold(db: Database) -> None:
    existing = _job(title="Data Scientist (H/F)")
    db.save_job(existing)
    embedder, _ = _counting_embedder([0.6, 0.8])
    emb.get_job_embedding(db, existing, model="m", embedder=embedder)

    incoming = _job(title="Data Scientist F/H", id="new-job-id")
    dupe = emb.find_near_duplicate(db, incoming, model="m", embedder=embedder)
    assert dupe == existing.id


def test_find_near_duplicate_preserves_distinct_roles(db: Database) -> None:
    """Same company + near-identical boilerplate must NOT collapse distinct roles."""
    existing = _job(title="Data Scientist")
    db.save_job(existing)
    embedder, _ = _counting_embedder([0.6, 0.8])
    emb.get_job_embedding(db, existing, model="m", embedder=embedder)

    incoming = _job(title="Senior Data Scientist", id="new-job-id")
    assert emb.find_near_duplicate(db, incoming, model="m", embedder=embedder) is None


def test_find_near_duplicate_title_word_order_and_punctuation(db: Database) -> None:
    existing = _job(title="Data Scientist")
    db.save_job(existing)
    embedder, _ = _counting_embedder([0.6, 0.8])
    emb.get_job_embedding(db, existing, model="m", embedder=embedder)

    incoming = _job(title="Scientist, Data", id="new-job-id")
    assert emb.find_near_duplicate(db, incoming, model="m", embedder=embedder) == existing.id


def test_find_near_duplicate_ignores_other_companies(db: Database) -> None:
    existing = _job(company="OtherCorp")
    db.save_job(existing)
    embedder, _ = _counting_embedder([0.6, 0.8])
    emb.get_job_embedding(db, existing, model="m", embedder=embedder)

    incoming = _job(company="Acme", id="new-job-id")
    assert emb.find_near_duplicate(db, incoming, model="m", embedder=embedder) is None


def test_find_near_duplicate_below_threshold_returns_none(db: Database) -> None:
    existing = _job()
    db.save_job(existing)
    db.save_embedding(existing.id, "job", "m", "hash-a", [1.0, 0.0])

    incoming = _job(id="new-job-id", description="Different role entirely")

    def _orthogonal(text: str, model: str) -> list[float]:
        return [0.0, 1.0]

    assert emb.find_near_duplicate(db, incoming, model="m", embedder=_orthogonal) is None


def test_find_near_duplicate_uses_hash_when_ollama_and_onnx_are_unavailable(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = _job(title="Data Scientist (H/F)")
    db.save_job(existing)
    monkeypatch.setattr(emb, "resolve_embed_model", lambda options=None, installed=None: None)
    monkeypatch.setattr(emb.onnx_embeddings, "is_available", lambda: False)
    vector = emb.hash_embeddings.embed_text(emb.job_embedding_text(existing))
    db.save_embedding(existing.id, "job", "hash-v1", "existing-hash", vector)

    incoming = _job(title="Data Scientist (H/F)", id="incoming")

    assert emb.find_near_duplicate(db, incoming, options=emb.EmbeddingOptions()) == existing.id


# ---- DB embedding storage ----

def test_save_and_get_embedding_roundtrip(db: Database) -> None:
    db.save_embedding("owner-1", "job", "model-x", "hash-1", [0.25, 0.75])
    row = db.get_embedding("owner-1", "job")
    assert row is not None
    assert row["model"] == "model-x"
    assert row["text_hash"] == "hash-1"
    assert row["vector"] == [0.25, 0.75]


def test_get_embedding_missing_returns_none(db: Database) -> None:
    assert db.get_embedding("nope", "job") is None


def test_delete_embedding_removes_row(db: Database) -> None:
    db.save_embedding("owner-1", "job", "model-x", "hash-1", [0.25, 0.75])
    db.delete_embedding("owner-1", "job")
    assert db.get_embedding("owner-1", "job") is None


def test_delete_embedding_missing_is_noop(db: Database) -> None:
    db.delete_embedding("nope", "job")


# ---- scorer blend ----

def test_score_job_without_semantic_is_unchanged() -> None:
    job, profile = _job(), _profile()
    baseline = score_job(job, profile)
    explicit_none = score_job(job, profile, semantic_score=None)
    assert baseline.total_score == explicit_none.total_score
    assert baseline.semantic_score is None
    assert not any("semantic" in note.lower() for note in baseline.notes)


def test_score_job_with_semantic_blends_and_records_note() -> None:
    job, profile = _job(), _profile()
    without = score_job(job, profile)
    with_high = score_job(job, profile, semantic_score=100)
    with_low = score_job(job, profile, semantic_score=0)
    assert with_high.semantic_score == 100
    assert with_low.semantic_score == 0
    assert with_high.total_score >= with_low.total_score
    # 15% weight: swing between semantic 0 and 100 should be about 15 points.
    assert (with_high.total_score - with_low.total_score) == pytest.approx(15, abs=1)
    assert any("semantic" in note.lower() for note in with_high.notes)
    assert without.total_score - 8 <= with_high.total_score <= without.total_score + 16


def test_score_job_semantic_respects_hard_caps() -> None:
    job = _job(description="French required for this role. Machine learning.")
    profile = _profile(languages=["English"])
    result = score_job(job, profile, semantic_score=100)
    assert result.total_score <= 25


# ---- pipeline integration (fail-soft, contract-preserving) ----

def test_add_job_skips_semantic_near_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from job_agent import pipeline
    from job_agent.config import AppConfig

    config = AppConfig(data_dir=tmp_path)
    known: dict = {"existing": None}
    monkeypatch.setattr(pipeline.embeddings, "find_near_duplicate", lambda db, job: known["existing"])

    first, created = pipeline.add_job_to_tracker(config, _job(title="Data Scientist"))
    assert created
    known["existing"] = first.id

    second, created_again = pipeline.add_job_to_tracker(
        config, _job(title="Scientist, Data", description="Slightly reworded posting.")
    )
    assert not created_again
    assert second.id == first.id


def test_semantic_duplicate_cleans_up_orphan_embedding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A deduped job is never inserted, so its cached vector must not linger."""
    from job_agent import pipeline
    from job_agent.config import AppConfig
    from job_agent.db.database import Database as Db

    config = AppConfig(data_dir=tmp_path)
    first, created = pipeline.add_job_to_tracker(config, _job(title="Data Scientist"))
    assert created

    # Different location → different exact fingerprint, so intake reaches the
    # semantic-dedup branch instead of the exact-match early return.
    incoming = _job(title="Data Scientist", id="incoming-dupe-id", location="Lyon")
    db2 = Db(config.db_path)
    db2.initialize()
    db2.save_embedding(incoming.id, "job", "m", "hash-x", [0.6, 0.8])
    monkeypatch.setattr(pipeline.embeddings, "find_near_duplicate", lambda db, job: first.id)

    _, created_again = pipeline.add_job_to_tracker(config, incoming)
    assert not created_again
    assert db2.get_embedding(incoming.id, "job") is None


def test_add_job_proceeds_when_semantic_check_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from job_agent import pipeline
    from job_agent.config import AppConfig

    def _boom(db, job):
        raise RuntimeError("ollama exploded")

    monkeypatch.setattr(pipeline.embeddings, "find_near_duplicate", _boom)
    config = AppConfig(data_dir=tmp_path)
    job, created = pipeline.add_job_to_tracker(config, _job())
    assert created
    assert job.title == "Data Scientist"


def test_score_and_save_blends_semantic_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from job_agent import pipeline
    from job_agent.config import AppConfig

    config = AppConfig(data_dir=tmp_path)
    monkeypatch.setattr(pipeline.embeddings, "find_near_duplicate", lambda db, job: None)
    job, _ = pipeline.add_job_to_tracker(config, _job())
    monkeypatch.setattr(pipeline.embeddings, "semantic_similarity", lambda job, profile, db: 90)
    scored = pipeline.score_and_save(config, job, _profile())
    assert any("semantic" in note.lower() for note in scored.fit_notes)


def test_score_and_save_unchanged_when_semantic_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from job_agent import pipeline
    from job_agent.config import AppConfig

    config = AppConfig(data_dir=tmp_path)
    monkeypatch.setattr(pipeline.embeddings, "find_near_duplicate", lambda db, job: None)
    job, _ = pipeline.add_job_to_tracker(config, _job())
    monkeypatch.setattr(pipeline.embeddings, "semantic_similarity", lambda job, profile, db: None)
    scored = pipeline.score_and_save(config, job, _profile())
    assert not any("semantic" in note.lower() for note in scored.fit_notes)
    assert scored.fit_score is not None
