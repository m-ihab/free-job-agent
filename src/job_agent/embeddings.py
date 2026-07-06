"""Local semantic embeddings via a locally-running Ollama server.

Enhancer only: every helper degrades to ``None`` when Ollama, the ``requests``
package, or an embedding-capable model is unavailable. The deterministic
scorer and pipeline never depend on this module succeeding.

Vectors are cached in the local SQLite ``embeddings`` table keyed by
``(owner_id, kind)`` with a text hash, so each job/profile is embedded once
per content change. No candidate data ever leaves the machine.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

from job_agent.polish import DEFAULT_BASE_URL, PolishOptions, available_ollama_models
from job_agent.schemas.candidate import CandidateProfile
from job_agent.schemas.job import JobListing

try:
    import requests
except Exception:  # pragma: no cover - requests is in install_requires
    requests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DEFAULT_EMBED_TIMEOUT = 30
DEFAULT_DUPE_THRESHOLD = 0.95
_MAX_EMBED_CHARS = 4000
PROFILE_OWNER_ID = "__profile__"

# Embedding-capable model families, best first. Chat models are never used for
# embeddings — if none of these are installed, semantic features stay off.
_PREFERRED_EMBED_MODELS = [
    "nomic-embed-text",
    "mxbai-embed-large",
    "bge-m3",
    "snowflake-arctic-embed",
    "granite-embedding",
    "all-minilm",
]

Embedder = Callable[[str, str], Optional[list[float]]]


@dataclass(frozen=True)
class EmbeddingOptions:
    base_url: str = DEFAULT_BASE_URL
    model: str = ""  # explicit override; empty = auto-detect
    timeout: int = DEFAULT_EMBED_TIMEOUT
    disabled: bool = False
    dupe_threshold: float = DEFAULT_DUPE_THRESHOLD

    @classmethod
    def from_env(cls) -> "EmbeddingOptions":
        return cls(
            base_url=os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            model=os.environ.get("JOB_AGENT_OLLAMA_EMBED_MODEL", "").strip(),
            timeout=int(os.environ.get("JOB_AGENT_OLLAMA_EMBED_TIMEOUT", str(DEFAULT_EMBED_TIMEOUT))),
            disabled=os.environ.get("JOB_AGENT_DISABLE_EMBEDDINGS", "").strip() in {"1", "true", "yes", "on"},
            dupe_threshold=float(os.environ.get("JOB_AGENT_EMBED_DUPE_THRESHOLD", str(DEFAULT_DUPE_THRESHOLD))),
        )


def _family(model_name: str) -> str:
    return model_name.split(":", 1)[0].strip().lower()


def resolve_embed_model(options: EmbeddingOptions | None = None, installed: list[str] | None = None) -> str | None:
    """Pick an installed embedding model, or None when semantic features are off."""
    options = options or EmbeddingOptions.from_env()
    if options.disabled:
        return None
    if installed is None:
        polish_options = PolishOptions(base_url=options.base_url, timeout=options.timeout)
        installed = available_ollama_models(polish_options)
    if not installed:
        return None
    if options.model:
        if options.model in installed:
            return options.model
        for model in installed:
            if _family(model) == _family(options.model):
                return model
        return None
    for preferred in _PREFERRED_EMBED_MODELS:
        for model in installed:
            if _family(model) == preferred:
                return model
    return None


def embed_text(text: str, options: EmbeddingOptions | None = None, model: str | None = None) -> list[float] | None:
    """Embed one text via Ollama ``/api/embed``. Returns None on any failure."""
    options = options or EmbeddingOptions.from_env()
    model = model or resolve_embed_model(options)
    if requests is None or not model or not text.strip():
        return None
    payload: dict[str, Any] = {"model": model, "input": text[:_MAX_EMBED_CHARS]}
    try:
        response = requests.post(options.base_url + "/api/embed", json=payload, timeout=options.timeout)
        response.raise_for_status()
        data = response.json()
    except Exception:
        logger.debug("Embedding request failed for model %s", model, exc_info=True)
        return None
    vectors = data.get("embeddings") if isinstance(data, dict) else None
    vector = vectors[0] if isinstance(vectors, list) and vectors else data.get("embedding") if isinstance(data, dict) else None
    if not isinstance(vector, list) or not vector:
        return None
    try:
        return [float(value) for value in vector]
    except (TypeError, ValueError):
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def job_embedding_text(job: JobListing) -> str:
    parts = [job.title, job.company, job.location or "", ", ".join(job.tech_stack), job.description[:2000]]
    return "\n".join(part for part in parts if part)


def profile_embedding_text(profile: CandidateProfile) -> str:
    parts = [
        ", ".join(profile.target_roles),
        ", ".join(profile.all_skill_names()),
        ", ".join(profile.target_locations),
        profile.summary,
    ]
    return "\n".join(part for part in parts if part)


def _text_hash(text: str, model: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()


def _default_embedder(options: EmbeddingOptions) -> Embedder:
    return lambda text, model: embed_text(text, options=options, model=model)


def _cached_embedding(db: Any, owner_id: str, kind: str, text: str, model: str, embedder: Embedder) -> list[float] | None:
    content_hash = _text_hash(text, model)
    row = db.get_embedding(owner_id, kind)
    if row and row.get("model") == model and row.get("text_hash") == content_hash:
        return row.get("vector")
    vector = embedder(text, model)
    if not vector:
        return None
    db.save_embedding(owner_id, kind, model, content_hash, vector)
    return vector


def get_job_embedding(db: Any, job: JobListing, *, model: str, embedder: Embedder | None = None,
                      options: EmbeddingOptions | None = None) -> list[float] | None:
    embedder = embedder or _default_embedder(options or EmbeddingOptions.from_env())
    return _cached_embedding(db, job.id, "job", job_embedding_text(job), model, embedder)


def get_profile_embedding(db: Any, profile: CandidateProfile, *, model: str, embedder: Embedder | None = None,
                          options: EmbeddingOptions | None = None) -> list[float] | None:
    embedder = embedder or _default_embedder(options or EmbeddingOptions.from_env())
    return _cached_embedding(db, PROFILE_OWNER_ID, "profile", profile_embedding_text(profile), model, embedder)


def semantic_similarity(job: JobListing, profile: CandidateProfile, db: Any, *,
                        options: EmbeddingOptions | None = None, model: str | None = None,
                        embedder: Embedder | None = None) -> int | None:
    """0-100 semantic fit between a job and the profile, or None when unavailable."""
    options = options or EmbeddingOptions.from_env()
    model = model or resolve_embed_model(options)
    if not model:
        return None
    job_vector = get_job_embedding(db, job, model=model, embedder=embedder, options=options)
    profile_vector = get_profile_embedding(db, profile, model=model, embedder=embedder, options=options)
    if not job_vector or not profile_vector:
        return None
    similarity = max(0.0, min(1.0, cosine_similarity(job_vector, profile_vector)))
    return round(similarity * 100)


# Job-title tokens that don't distinguish roles: gender notation on French/
# German postings ("(H/F)", "F/H", "m/w/d") reduced to single letters or
# letter runs after punctuation stripping.
_TITLE_MARKER_TOKENS = {"h", "f", "m", "w", "d", "x", "hf", "fh", "mw", "mwd", "mfd", "fhx", "hfx"}


def _title_tokens(title: str) -> frozenset[str]:
    cleaned = "".join(ch if ch.isalnum() else " " for ch in (title or "").lower())
    return frozenset(tok for tok in cleaned.split() if tok not in _TITLE_MARKER_TOKENS)


def same_role_title(a: str, b: str) -> bool:
    """True when two titles name the same role (order/punct/gender-marker insensitive).

    'Data Scientist (H/F)' == 'Scientist, Data' but != 'Senior Data Scientist':
    an extra token like 'senior' is a different role, never a duplicate.
    """
    tokens_a, tokens_b = _title_tokens(a), _title_tokens(b)
    return bool(tokens_a) and tokens_a == tokens_b


def find_near_duplicate(db: Any, job: JobListing, *, options: EmbeddingOptions | None = None,
                        model: str | None = None, embedder: Embedder | None = None) -> str | None:
    """Return the id of an existing same-company job that is a near-duplicate.

    Company-scoped on purpose: cross-company matches at high cosine are usually
    boilerplate postings, not the same role. A shared-boilerplate description
    can push two *different* roles past the cosine threshold, so the titles
    must also name the same role. Returns None when embeddings are unavailable
    so intake never depends on Ollama.
    """
    options = options or EmbeddingOptions.from_env()
    model = model or resolve_embed_model(options)
    if not model:
        return None
    vector = get_job_embedding(db, job, model=model, embedder=embedder, options=options)
    if not vector:
        return None
    best_id, best_similarity = None, 0.0
    for row in db.list_job_embeddings_for_company(job.company):
        if row["owner_id"] == job.id or row.get("model") != model:
            continue
        if not same_role_title(job.title, row.get("title") or ""):
            continue
        similarity = cosine_similarity(vector, row["vector"])
        if similarity > best_similarity:
            best_id, best_similarity = row["owner_id"], similarity
    if best_id is not None and best_similarity >= options.dupe_threshold:
        return best_id
    return None
