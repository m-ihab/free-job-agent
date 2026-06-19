"""Round-2 behavioural tests for ``job_agent.cv_studio`` deterministic ops.

Covers the compile-dependent and guard branches not exercised by
``test_cv_studio_core``: ``compile_preview`` (not-a-document / no-source /
compile-failed / success), ``promote_draft_to_main`` (no draft / no profiles dir /
backup+copy), ``single_page_guard`` + ``auto_fit_one_page`` page-count branches,
and ``ats_keyword_radar`` role fallback. The LaTeX compiler is always mocked,
so no real LaTeX runs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.config import AppConfig
from job_agent import cv_studio
from job_agent.cv_studio import (
    ats_keyword_radar,
    auto_fit_one_page,
    compile_preview,
    promote_draft_to_main,
    set_studio_language,
    single_page_guard,
)
from job_agent.cv_studio_core import _draft_path


_DOC = "\n".join([
    r"\documentclass[11pt,a4paper]{moderncv}",
    r"\newcommand{\cvlang}{en}",
    r"\begin{document}",
    r"\section{\sectedu}",
    r"Education body",
    r"\end{document}",
])


def _make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    data_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir)


@pytest.fixture
def patched_latex(monkeypatch):
    """Mock the LaTeX seam so ``compile_preview`` writes a fake PDF instead.

    Returns a small controller letting each test choose page count / failure.
    """
    state = {"pages": 1, "fail": False}

    def fake_copy_assets(profiles_dir, studio):
        return None

    def fake_compile(tex_path, pdf_path):
        if state["fail"]:
            raise cv_studio.LatexCompileError("boom: undefined control sequence")
        # Write a fake PDF whose page-marker count matches the requested pages.
        markers = b"/Type /Page" * state["pages"]
        Path(pdf_path).write_bytes(b"%PDF-1.4\n" + markers + b"\n%%EOF")

    monkeypatch.setattr(cv_studio, "copy_latex_assets", fake_copy_assets)
    monkeypatch.setattr(cv_studio, "compile_latex_to_pdf", fake_compile)
    return state


# --- compile_preview ------------------------------------------------------


def test_compile_preview_rejects_non_document_text(tmp_path, patched_latex):
    config = _make_config(tmp_path)
    result = compile_preview(config, "just some JSON, not a tex document")
    assert result["ok"] is False
    assert result["reason"] == "not_latex_document"


def test_compile_preview_no_source_when_nothing_present(tmp_path, patched_latex):
    config = _make_config(tmp_path)  # no draft, no main.tex
    result = compile_preview(config, None)
    assert result["ok"] is False
    assert result["reason"] == "no_source"


def test_compile_preview_reports_compile_failure(tmp_path, patched_latex):
    config = _make_config(tmp_path)
    patched_latex["fail"] = True
    result = compile_preview(config, _DOC)
    assert result["ok"] is False
    assert result["reason"] == "compile_failed"
    assert "boom" in result["log"]


def test_compile_preview_success_returns_pdf_path(tmp_path, patched_latex):
    config = _make_config(tmp_path)
    result = compile_preview(config, _DOC)
    assert result["ok"] is True
    assert Path(result["pdf_path"]).exists()


def test_compile_preview_uses_draft_when_no_text(tmp_path, patched_latex):
    config = _make_config(tmp_path)
    _draft_path(config).write_text(_DOC, encoding="utf-8")
    result = compile_preview(config, None)
    assert result["ok"] is True


# --- promote_draft_to_main ------------------------------------------------


def test_promote_draft_returns_no_draft_when_missing(tmp_path):
    config = _make_config(tmp_path)
    assert promote_draft_to_main(config) == {"ok": False, "reason": "no_draft"}


def test_promote_draft_copies_to_main_with_backup(tmp_path):
    config = _make_config(tmp_path)
    main_path = Path(config.profiles_dir) / "main.tex"
    main_path.write_text("OLD main", encoding="utf-8")
    _draft_path(config).write_text("NEW draft", encoding="utf-8")

    result = promote_draft_to_main(config)

    assert result["ok"] is True
    assert main_path.read_text(encoding="utf-8") == "NEW draft"
    assert main_path.with_suffix(".bak").read_text(encoding="utf-8") == "OLD main"


# --- single_page_guard ----------------------------------------------------


def test_single_page_guard_reports_single_page(tmp_path, patched_latex):
    config = _make_config(tmp_path)
    patched_latex["pages"] = 1
    result = single_page_guard(config, _DOC)
    assert result["ok"] is True
    assert result["single_page"] is True
    assert result["trims"] == []


def test_single_page_guard_suggests_trims_when_two_pages(tmp_path, patched_latex):
    config = _make_config(tmp_path)
    patched_latex["pages"] = 2
    result = single_page_guard(config, _DOC)
    assert result["ok"] is True
    assert result["single_page"] is False
    assert len(result["trims"]) >= 1


def test_single_page_guard_propagates_compile_failure(tmp_path, patched_latex):
    config = _make_config(tmp_path)
    patched_latex["fail"] = True
    result = single_page_guard(config, _DOC)
    assert result["ok"] is False
    assert result["reason"] == "compile_failed"


# --- auto_fit_one_page ----------------------------------------------------


def test_auto_fit_rejects_non_document(tmp_path, patched_latex):
    config = _make_config(tmp_path)
    result = auto_fit_one_page(config, "not a document")
    assert result["ok"] is False
    assert result["reason"] == "not_latex_document"


def test_auto_fit_no_op_when_already_single_page(tmp_path, patched_latex):
    config = _make_config(tmp_path)
    patched_latex["pages"] = 1
    result = auto_fit_one_page(config, _DOC)
    assert result["changed"] is False
    assert result["text"] == _DOC


def test_auto_fit_applies_typography_changes_when_overflowing(tmp_path, patched_latex):
    config = _make_config(tmp_path)
    patched_latex["pages"] = 2  # forces the "needs fitting" branch
    result = auto_fit_one_page(config, _DOC)
    # The 11pt -> 10pt substitution fires on this document class.
    assert "10pt" in result["text"]
    assert result["changed"] is True
    assert result["steps"]


# --- set_studio_language --------------------------------------------------


def test_set_studio_language_no_toggle_when_command_absent(tmp_path):
    config = _make_config(tmp_path)
    # main.tex without \cvlang -> no_language_toggle reason.
    (Path(config.profiles_dir) / "main.tex").write_text(
        r"\begin{document}\section{X}\end{document}", encoding="utf-8"
    )
    result = set_studio_language(config, "fr")
    assert result["ok"] is False
    assert result["reason"] == "no_language_toggle"


# --- ats_keyword_radar role fallback --------------------------------------


def test_ats_keyword_radar_falls_back_to_data_scientist_pack(tmp_path):
    config = _make_config(tmp_path)
    result = ats_keyword_radar(config, "Python and SQL and Pandas", role="unknown_role")
    # Unknown role -> data_scientist pack; present keywords detected.
    assert "Python" in result["present"]
    assert result["role"] == "unknown_role"
    assert 0 <= result["coverage"] <= 100
