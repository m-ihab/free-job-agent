"""Hermetic tests for the deterministic hashing embedding tier."""
from __future__ import annotations

import math

import pytest

from job_agent import hash_embeddings as hashing


def test_hash_embedding_is_deterministic_and_uses_stable_identity() -> None:
    first = hashing.embed_text("Python SQL python")
    second = hashing.embed_text("Python SQL python")

    assert hashing.MODEL_ID == "hash-v1"
    assert first == second


def test_hash_embedding_has_expected_dimension_and_unit_norm() -> None:
    vector = hashing.embed_text("Machine learning with Python and SQL")

    assert len(vector) == 256
    assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(1.0)


def test_hash_embedding_batch_matches_single_text_calls() -> None:
    texts = ["Data Scientist", "ML Engineer", ""]

    assert hashing.embed_texts(texts) == [hashing.embed_text(text) for text in texts]
    assert hashing.embed_text("") == [0.0] * 256
