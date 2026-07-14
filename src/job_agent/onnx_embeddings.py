"""Optional all-MiniLM-L6-v2 ONNX embeddings with TOFU integrity checks."""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
import math
import re
import shutil
from pathlib import Path
from typing import Any, Sequence
from urllib.request import urlopen

from job_agent.config import AppConfig

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
# TODO(OWNER): FREEZE THIS TO A REVIEWED UPSTREAM COMMIT SHA; `main` IS NOT IMMUTABLE.
REVISION = "main"
MODEL_ID = f"onnx:{MODEL_NAME}@{REVISION}"
BASE_URL = f"https://huggingface.co/sentence-transformers/{MODEL_NAME}/resolve/{REVISION}"
MODEL_URL = f"{BASE_URL}/onnx/model.onnx"
VOCAB_URL = f"{BASE_URL}/vocab.txt"
MIN_MODEL_BYTES = 50 * 1024 * 1024
MIN_VOCAB_BYTES = 100 * 1024
MAX_LEN = 256
_FILES = ("model.onnx", "vocab.txt", "manifest.json")
_SESSIONS: dict[str, Any] = {}
_BASIC_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def _model_dir(data_dir: Path | None = None) -> Path:
    root = Path(data_dir) if data_dir is not None else AppConfig.load().data_dir
    return root.expanduser().resolve() / "models" / MODEL_NAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_artifacts(model_dir: Path) -> None:
    for name in (*_FILES, "model.onnx.download", "vocab.txt.download"):
        try:
            (model_dir / name).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove invalid ONNX artifact %s", model_dir / name, exc_info=True)


def _download_file(url: str, destination: Path) -> None:
    with urlopen(url, timeout=30) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def _verified_manifest(model_dir: Path) -> bool:
    model_path, vocab_path = model_dir / "model.onnx", model_dir / "vocab.txt"
    try:
        manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
        files = manifest["files"]
        return (
            manifest["revision"] == REVISION
            and model_path.stat().st_size > MIN_MODEL_BYTES
            and vocab_path.stat().st_size > MIN_VOCAB_BYTES
            and files["model.onnx"] == _sha256(model_path)
            and files["vocab.txt"] == _sha256(vocab_path)
        )
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return False


def ensure_model_files(data_dir: Path | None = None) -> tuple[Path, Path] | None:
    """Download once, then require the first-use hashes on every later load."""
    model_dir = _model_dir(data_dir)
    manifest_path = model_dir / "manifest.json"
    model_path, vocab_path = model_dir / "model.onnx", model_dir / "vocab.txt"
    if manifest_path.exists():
        if _verified_manifest(model_dir):
            return model_path, vocab_path
        logger.warning("ONNX embedding integrity check failed; deleting cached model")
        _remove_artifacts(model_dir)
        return None
    model_dir.mkdir(parents=True, exist_ok=True)
    _remove_artifacts(model_dir)
    model_tmp, vocab_tmp = model_dir / "model.onnx.download", model_dir / "vocab.txt.download"
    try:
        _download_file(MODEL_URL, model_tmp)
        _download_file(VOCAB_URL, vocab_tmp)
        if model_tmp.stat().st_size <= MIN_MODEL_BYTES or vocab_tmp.stat().st_size <= MIN_VOCAB_BYTES:
            raise ValueError("downloaded ONNX model files failed minimum-size checks")
        model_tmp.replace(model_path)
        vocab_tmp.replace(vocab_path)
        manifest = {
            "revision": REVISION,
            "files": {"model.onnx": _sha256(model_path), "vocab.txt": _sha256(vocab_path)},
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return model_path, vocab_path
    except (OSError, ValueError) as exc:
        logger.warning("ONNX embedding model download rejected: %s", exc)
        _remove_artifacts(model_dir)
        return None


def load_vocab(path: Path) -> dict[str, int]:
    return {token: index for index, token in enumerate(path.read_text(encoding="utf-8").splitlines())}


def wordpiece_ids(text: str, vocab: dict[str, int], max_len: int = MAX_LEN) -> list[int]:
    pieces: list[int] = []
    unknown = vocab["[UNK]"]
    for token in _BASIC_TOKEN_RE.findall(text.lower()):
        start, token_ids = 0, []
        while start < len(token):
            end, piece_id = len(token), None
            while start < end:
                piece = token[start:end] if start == 0 else "##" + token[start:end]
                if piece in vocab:
                    piece_id = vocab[piece]
                    break
                end -= 1
            if piece_id is None:
                token_ids = [unknown]
                break
            token_ids.append(piece_id)
            start = end
        pieces.extend(token_ids)
    return [vocab["[CLS]"], *pieces[: max_len - 2], vocab["[SEP]"]]


def encode_batch(texts: list[str], vocab: dict[str, int]) -> tuple[list[list[int]], list[list[int]]]:
    rows = [wordpiece_ids(text, vocab) for text in texts]
    width = max((len(row) for row in rows), default=0)
    masks = [[1] * len(row) + [0] * (width - len(row)) for row in rows]
    return [row + [vocab["[PAD]"]] * (width - len(row)) for row in rows], masks


def mean_pool(hidden: Sequence[Sequence[Sequence[float]]], masks: list[list[int]]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for tokens, mask in zip(hidden, masks):
        width = len(tokens[0]) if len(tokens) else 0
        pooled = [sum(float(token[i]) * bit for token, bit in zip(tokens, mask)) for i in range(width)]
        count = max(sum(mask), 1)
        pooled = [value / count for value in pooled]
        norm = math.sqrt(sum(value * value for value in pooled))
        vectors.append([value / norm for value in pooled] if norm else pooled)
    return vectors


def _load_session(data_dir: Path | None = None) -> tuple[Any, Path] | None:
    try:
        runtime = importlib.import_module("onnxruntime")
    except ImportError:
        logger.debug("onnxruntime is not installed; ONNX embedding tier unavailable")
        return None
    files = ensure_model_files(data_dir)
    if files is None:
        return None
    model_path, vocab_path = files
    key = str(model_path)
    if key not in _SESSIONS:
        try:
            _SESSIONS[key] = runtime.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        except Exception:
            logger.debug("Could not load ONNX embedding model", exc_info=True)
            return None
    return _SESSIONS[key], vocab_path


def is_available(data_dir: Path | None = None) -> bool:
    return _load_session(data_dir) is not None


def embed_texts(texts: list[str], data_dir: Path | None = None) -> list[list[float]] | None:
    if not texts:
        return []
    loaded = _load_session(data_dir)
    if loaded is None:
        return None
    session, vocab_path = loaded
    try:
        numpy = importlib.import_module("numpy")
        input_ids, masks = encode_batch(texts, load_vocab(vocab_path))
        arrays = {"input_ids": input_ids, "attention_mask": masks, "token_type_ids": [[0] * len(row) for row in input_ids]}
        names = {item.name for item in session.get_inputs()}
        feeds = {name: numpy.asarray(value, dtype=numpy.int64) for name, value in arrays.items() if name in names}
        hidden = session.run(None, feeds)[0]
        return mean_pool(hidden, masks)
    except Exception:
        logger.debug("ONNX embedding inference failed", exc_info=True)
        return None
