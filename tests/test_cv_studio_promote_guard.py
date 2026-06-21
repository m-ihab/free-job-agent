"""Tests for CV Studio promote validation and version history.

The promote path must refuse any non-LaTeX / truncated draft so it cannot
overwrite a real ``profiles/main.tex``, snapshot prior versions, and restore.
"""
from __future__ import annotations

from pathlib import Path

from job_agent.config import AppConfig
from job_agent.cv_studio import (
    list_main_versions,
    promote_draft_to_main,
    restore_main_version,
    save_studio_draft,
)
from job_agent.cv_studio_core import (
    is_valid_latex_cv,
    snapshot_main_tex,
    validate_promote,
)

# A minimal but complete moderncv-style document, comfortably over MIN_TEX_BYTES.
VALID_CV = r"""
\documentclass[11pt,a4paper,sans]{moderncv}
\moderncvstyle{banking}
\moderncvcolor{blue}
\name{Mohamed}{Abdelkarim}
\begin{document}
\makecvtitle
\section{Experience}
\cventry{2024}{Data Scientist}{Acme}{Paris}{}{Built ML pipelines.}
\end{document}
""".strip()


def _make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    data_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir)


# --- is_valid_latex_cv ------------------------------------------------------


def test_placeholder_draft_is_not_valid_latex():
    assert is_valid_latex_cv("draft") is False
    assert is_valid_latex_cv("") is False
    assert is_valid_latex_cv(None) is False


def test_json_blob_is_not_valid_latex():
    assert is_valid_latex_cv('{"contact": {"name": "X"}}') is False


def test_complete_document_is_valid_latex():
    assert is_valid_latex_cv(VALID_CV) is True


def test_document_missing_begin_document_is_invalid():
    only_class = r"\documentclass{moderncv}" + " % padding " * 40
    assert is_valid_latex_cv(only_class) is False


# --- validate_promote shrink guard -----------------------------------------


def test_validate_promote_blocks_suspicious_shrink(tmp_path):
    config = _make_config(tmp_path)
    main = Path(config.profiles_dir) / "main.tex"
    main.write_text(VALID_CV + "\n" * 1500, encoding="utf-8")  # clearly larger existing CV
    tiny_but_valid = VALID_CV  # valid, but far smaller than current
    ok, reason = validate_promote(tiny_but_valid, main)
    assert ok is False
    assert reason == "suspicious_shrink"


def test_validate_promote_allows_replacing_placeholder_main(tmp_path):
    config = _make_config(tmp_path)
    main = Path(config.profiles_dir) / "main.tex"
    main.write_text("draft", encoding="utf-8")  # current main is itself junk
    ok, reason = validate_promote(VALID_CV, main)
    assert ok is True
    assert reason == ""


# --- promote_draft_to_main end-to-end --------------------------------------


def test_promote_rejects_placeholder_and_leaves_main_untouched(tmp_path):
    config = _make_config(tmp_path)
    main = Path(config.profiles_dir) / "main.tex"
    main.write_text(VALID_CV, encoding="utf-8")
    save_studio_draft(config, "draft")

    result = promote_draft_to_main(config)

    assert result["ok"] is False
    assert result["reason"] == "not_latex_document"
    assert main.read_text(encoding="utf-8") == VALID_CV


def test_promote_valid_draft_writes_main_and_snapshots(tmp_path):
    config = _make_config(tmp_path)
    main = Path(config.profiles_dir) / "main.tex"
    original = VALID_CV + "\n% original\n"
    main.write_text(original, encoding="utf-8")
    updated = VALID_CV + "\n% updated edition with more content here padding padding\n"
    save_studio_draft(config, updated)

    result = promote_draft_to_main(config)

    assert result["ok"] is True
    assert main.read_text(encoding="utf-8") == updated
    # The prior main.tex was snapshotted to history.
    versions = list_main_versions(config)
    assert len(versions) == 1


def test_restore_version_round_trips(tmp_path):
    config = _make_config(tmp_path)
    main = Path(config.profiles_dir) / "main.tex"
    v1 = VALID_CV + "\n% version one content padding padding padding padding\n"
    main.write_text(v1, encoding="utf-8")
    snapshot_main_tex(config)  # snapshot v1
    v2 = VALID_CV + "\n% version two replaces it padding padding padding\n"
    main.write_text(v2, encoding="utf-8")

    versions = list_main_versions(config)
    assert len(versions) == 1
    result = restore_main_version(config, versions[0]["name"])

    assert result["ok"] is True
    assert main.read_text(encoding="utf-8") == v1


def test_restore_rejects_bad_version_name(tmp_path):
    config = _make_config(tmp_path)
    (Path(config.profiles_dir) / "main.tex").write_text(VALID_CV, encoding="utf-8")
    result = restore_main_version(config, "../../etc/passwd")
    assert result["ok"] is False
    assert result["reason"] == "bad_version_name"
