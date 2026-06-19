"""Behavioural tests for CV template import — remaining branches.

Covers each supported-extension routing branch (tex/pdf/docx/jpg/png/support),
backup creation on overwrite, the safe-filename fallback, and the validation
error paths (invalid base64, empty, oversized) not exercised by the existing
test_cv_template.py.
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from job_agent.config import AppConfig
from job_agent import cv_template as cv


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig(data_dir=tmp_path / "data", profiles_dir=tmp_path / "profiles",
                    outputs_dir=tmp_path / "outputs")
    cfg.ensure_dirs()
    return cfg


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ── extension routing ────────────────────────────────────────────────────────

@pytest.mark.parametrize("filename,expected_name", [
    ("resume.docx", "source_cv.docx"),
    ("photo.jpg", "me.jpg"),
    ("photo.jpeg", "me.jpg"),
    ("photo.png", "me.png"),
    ("macros.sty", "macros.sty"),
    ("style.cls", "style.cls"),
])
def test_import_routes_to_expected_target(config, filename, expected_name):
    result = cv.import_cv_template_upload(config, filename=filename, content_base64=_b64(b"content-bytes"))
    assert result["ok"] is True
    assert Path(result["target"]).name == expected_name
    assert (Path(config.profiles_dir) / expected_name).exists()


def test_import_pdf_backs_up_existing(config):
    cv.import_cv_template_upload(config, filename="cv.pdf", content_base64=_b64(b"v1"))
    result = cv.import_cv_template_upload(config, filename="cv.pdf", content_base64=_b64(b"v2"))
    assert result["backups"], "Overwriting an existing PDF should produce a backup"
    backup = Path(result["backups"][0])
    assert backup.exists()
    assert backup.read_bytes() == b"v1"
    assert (Path(config.profiles_dir) / "CV.pdf").read_bytes() == b"v2"


def test_import_sanitizes_unsafe_filename(config):
    result = cv.import_cv_template_upload(
        config, filename="../../weird name!.sty", content_base64=_b64(b"x"))
    target = Path(result["target"])
    assert ".." not in target.name
    assert target.name.endswith(".sty")


# ── validation errors ────────────────────────────────────────────────────────

def test_import_rejects_invalid_base64(config):
    with pytest.raises(ValueError, match="Invalid uploaded file content"):
        cv.import_cv_template_upload(config, filename="a.tex", content_base64="!!!not-base64!!!")


def test_import_rejects_empty_file(config):
    with pytest.raises(ValueError, match="empty"):
        cv.import_cv_template_upload(config, filename="a.tex", content_base64=_b64(b""))


def test_import_rejects_oversized_file(config):
    big = b"x" * (15 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="too large"):
        cv.import_cv_template_upload(config, filename="a.pdf", content_base64=_b64(big))


# ── safe filename helper ─────────────────────────────────────────────────────

def test_safe_filename_falls_back_for_empty():
    assert cv._safe_filename("") == "uploaded_cv_template"
    assert cv._safe_filename("/path/to/cv.tex") == "cv.tex"
