"""Deterministic, dependency-free feature-hashing embeddings."""
from __future__ import annotations

import hashlib
import logging
import math
import re

logger = logging.getLogger(__name__)

DIMENSION = 256
MODEL_ID = "hash-v1"
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_TITLE_MARKERS = {"h", "f", "m", "w", "d", "x", "hf", "fh", "mw", "mwd", "mfd", "fhx", "hfx"}


def _unit_vector(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values] if norm else values


def embed_text(text: str) -> list[float]:
    """Hash lowercase word counts into a stable, L2-normalized vector."""
    vector = [0.0] * DIMENSION
    tokens = _WORD_RE.findall(text.lower())
    if not tokens:
        logger.debug("Hash embedding received no word tokens")
        return vector
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8"), usedforsecurity=False).digest()
        bucket = int.from_bytes(digest, "big") % DIMENSION
        sign = -1.0 if digest[0] & 1 else 1.0
        vector[bucket] += sign
    return _unit_vector(vector)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch with deterministic feature hashing."""
    return [embed_text(text) for text in texts]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if not norm_a or not norm_b:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)


def same_role_title(a: str, b: str) -> bool:
    """Compare role titles while ignoring order, punctuation, and gender markers."""
    def tokens(title: str) -> frozenset[str]:
        cleaned = "".join(char if char.isalnum() else " " for char in title.lower())
        return frozenset(token for token in cleaned.split() if token not in _TITLE_MARKERS)

    tokens_a, tokens_b = tokens(a or ""), tokens(b or "")
    return bool(tokens_a) and tokens_a == tokens_b
