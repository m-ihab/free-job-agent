"""Hermetic tests for the optional ONNX embedding tier."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from job_agent import onnx_embeddings as onnx


VOCAB = "\n".join(
    ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "hello", "world", "##s", "!", "un", "##aff", "##able"]
)


def _write_vocab(path: Path) -> None:
    path.write_text(VOCAB, encoding="utf-8")


def _fake_download(url: str, destination: Path) -> None:
    payload = b"model-payload" if url.endswith("model.onnx") else VOCAB.encode("utf-8")
    destination.write_bytes(payload)


def test_wordpiece_uses_exact_ids_and_continuation_tokens(tmp_path: Path) -> None:
    vocab_path = tmp_path / "vocab.txt"
    _write_vocab(vocab_path)
    vocab = onnx.load_vocab(vocab_path)

    ids = onnx.wordpiece_ids("Hello worlds! unaffable MISSING", vocab)

    assert ids == [2, 4, 5, 6, 7, 8, 9, 10, 1, 3]


def test_wordpiece_truncates_to_max_len_and_keeps_sep(tmp_path: Path) -> None:
    vocab_path = tmp_path / "vocab.txt"
    _write_vocab(vocab_path)

    ids = onnx.wordpiece_ids("hello hello hello hello hello", onnx.load_vocab(vocab_path), max_len=5)

    assert ids == [2, 4, 4, 4, 3]


def test_encode_batch_pads_ids_and_attention_mask(tmp_path: Path) -> None:
    vocab_path = tmp_path / "vocab.txt"
    _write_vocab(vocab_path)

    input_ids, attention_mask = onnx.encode_batch(
        ["hello", "hello worlds!"], onnx.load_vocab(vocab_path)
    )

    assert input_ids == [[2, 4, 3, 0, 0, 0], [2, 4, 5, 6, 7, 3]]
    assert attention_mask == [[1, 1, 1, 0, 0, 0], [1, 1, 1, 1, 1, 1]]


def test_mean_pool_uses_mask_and_l2_normalizes() -> None:
    hidden = [[[3.0, 4.0], [30.0, 40.0], [0.0, 0.0]]]

    assert onnx.mean_pool(hidden, [[1, 0, 1]])[0] == pytest.approx([0.6, 0.8])


def test_first_download_writes_tofu_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onnx, "MIN_MODEL_BYTES", 4)
    monkeypatch.setattr(onnx, "MIN_VOCAB_BYTES", 4)
    monkeypatch.setattr(onnx, "_download_file", _fake_download)

    paths = onnx.ensure_model_files(tmp_path)

    assert paths is not None
    model_path, vocab_path = paths
    manifest = json.loads((model_path.parent / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["revision"] == onnx.REVISION == "main"
    assert manifest["files"]["model.onnx"] == hashlib.sha256(model_path.read_bytes()).hexdigest()
    assert manifest["files"]["vocab.txt"] == hashlib.sha256(vocab_path.read_bytes()).hexdigest()


def test_valid_manifest_verifies_without_redownload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onnx, "MIN_MODEL_BYTES", 4)
    monkeypatch.setattr(onnx, "MIN_VOCAB_BYTES", 4)
    monkeypatch.setattr(onnx, "_download_file", _fake_download)
    first = onnx.ensure_model_files(tmp_path)

    def _unexpected_download(url: str, destination: Path) -> None:
        raise AssertionError(f"unexpected download: {url} -> {destination}")

    monkeypatch.setattr(onnx, "_download_file", _unexpected_download)

    assert onnx.ensure_model_files(tmp_path) == first


def test_manifest_mismatch_deletes_files_and_does_not_redownload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(onnx, "MIN_MODEL_BYTES", 4)
    monkeypatch.setattr(onnx, "MIN_VOCAB_BYTES", 4)
    monkeypatch.setattr(onnx, "_download_file", _fake_download)
    paths = onnx.ensure_model_files(tmp_path)
    assert paths is not None
    model_path, vocab_path = paths
    manifest_path = model_path.parent / "manifest.json"
    model_path.write_bytes(b"tampered-model")

    assert onnx.ensure_model_files(tmp_path) is None
    assert not model_path.exists()
    assert not vocab_path.exists()
    assert not manifest_path.exists()


def test_minimum_size_rejection_removes_downloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onnx, "_download_file", _fake_download)

    assert onnx.ensure_model_files(tmp_path) is None
    model_dir = tmp_path / "models" / "all-MiniLM-L6-v2"
    assert not (model_dir / "model.onnx").exists()
    assert not (model_dir / "vocab.txt").exists()
    assert not (model_dir / "manifest.json").exists()


def test_missing_onnxruntime_does_not_attempt_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "onnxruntime", None)

    def _unexpected_download(url: str, destination: Path) -> None:
        raise AssertionError(f"unexpected download: {url} -> {destination}")

    monkeypatch.setattr(onnx, "_download_file", _unexpected_download)

    assert not onnx.is_available(tmp_path)


def test_embed_texts_uses_mocked_onnxruntime_and_exact_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path, vocab_path = tmp_path / "model.onnx", tmp_path / "vocab.txt"
    model_path.write_bytes(b"model")
    _write_vocab(vocab_path)
    seen: dict[str, object] = {}

    class FakeSession:
        def __init__(self, path: str, providers: list[str]) -> None:
            seen["path"] = path
            seen["providers"] = providers

        def get_inputs(self) -> list[SimpleNamespace]:
            return [SimpleNamespace(name=name) for name in ("input_ids", "attention_mask", "token_type_ids")]

        def run(self, outputs: object, feeds: dict[str, object]) -> list[object]:
            seen["feeds"] = feeds
            return [[[[3.0, 4.0], [3.0, 4.0], [3.0, 4.0]]]]

    fake_ort = SimpleNamespace(InferenceSession=FakeSession)
    fake_numpy = SimpleNamespace(int64="int64", asarray=lambda value, dtype: value)
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setitem(sys.modules, "numpy", fake_numpy)
    monkeypatch.setattr(onnx, "ensure_model_files", lambda data_dir=None: (model_path, vocab_path))
    onnx._SESSIONS.clear()

    vectors = onnx.embed_texts(["hello"], data_dir=tmp_path)

    assert vectors is not None
    assert vectors[0] == [0.6, 0.8]
    assert seen["feeds"] == {
        "input_ids": [[2, 4, 3]],
        "attention_mask": [[1, 1, 1]],
        "token_type_ids": [[0, 0, 0]],
    }
