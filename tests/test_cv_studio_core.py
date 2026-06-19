"""Behavioural tests for CV Studio draft/active text + section operations.

Uses a temp data/profiles dir via AppConfig so file effects are observable.
No LaTeX compiler is invoked (compile-dependent paths are not exercised here).
"""
from __future__ import annotations

from pathlib import Path


from job_agent.config import AppConfig
from job_agent.cv_studio import (
    load_studio,
    reorder_sections,
    reset_studio_draft,
    save_studio_draft,
    section_display_name,
    set_studio_language,
    swap_studio_sections,
)
from job_agent.cv_studio_core import _active_cv_text, _draft_path


_TEMPLATE = "\n".join([
    r"\newcommand{\cvlang}{en}",
    r"\begin{document}",
    r"\section{\sectedu}",
    r"Education body",
    r"\section{\sectexp}",
    r"Experience body",
    r"\section{\sectskills}",
    r"Skills body",
    r"\end{document}",
])


def _make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    data_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir)


def _write_main(config: AppConfig, text: str = _TEMPLATE) -> Path:
    main = Path(config.profiles_dir) / "main.tex"
    main.write_text(text, encoding="utf-8")
    return main


# --- active text resolution ----------------------------------------------


def test_active_cv_text_prefers_draft_over_main(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    _write_main(config, "MAIN content")
    _draft_path(config).write_text("DRAFT content", encoding="utf-8")

    # Act
    text, path, origin = _active_cv_text(config)

    # Assert
    assert text == "DRAFT content"
    assert origin == "draft"


def test_active_cv_text_falls_back_to_main(tmp_path):
    # Arrange: no draft exists.
    config = _make_config(tmp_path)
    _write_main(config, "MAIN content")

    # Act
    text, path, origin = _active_cv_text(config)

    # Assert
    assert text == "MAIN content"
    assert origin == "main"


def test_active_cv_text_empty_when_nothing_present(tmp_path):
    config = _make_config(tmp_path)
    text, path, origin = _active_cv_text(config)
    assert text == ""
    assert origin == "empty"


# --- save / reset draft ---------------------------------------------------


def test_save_studio_draft_writes_file_and_reports_size(tmp_path):
    # Arrange
    config = _make_config(tmp_path)

    # Act
    result = save_studio_draft(config, "hello world")

    # Assert
    assert result["ok"] is True
    assert result["size"] == len("hello world")
    assert _draft_path(config).read_text(encoding="utf-8") == "hello world"


def test_reset_studio_draft_deletes_draft(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    save_studio_draft(config, "to be removed")
    assert _draft_path(config).exists()

    # Act
    reset_studio_draft(config)

    # Assert
    assert not _draft_path(config).exists()


# --- load_studio ----------------------------------------------------------


def test_load_studio_extracts_sections_and_language(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    _write_main(config)

    # Act
    state = load_studio(config)

    # Assert
    assert state["origin"] == "main"
    assert state["language"] == "en"
    assert "sectedu" in state["sections"]
    assert state["section_display"]["sectedu"] == "Education"


# --- section display name -------------------------------------------------


def test_section_display_name_maps_known_tokens():
    assert section_display_name("sectproj") == "Projects"
    assert section_display_name("\\sectlang") == "Languages"


def test_section_display_name_echoes_unknown_literal():
    assert section_display_name("Publications") == "Publications"
    assert section_display_name("") == "(section)"


# --- language switch ------------------------------------------------------


def test_set_studio_language_switches_to_fr_and_writes_draft(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    _write_main(config)

    # Act
    result = set_studio_language(config, "fr")

    # Assert
    assert result["ok"] is True
    assert result["language"] == "fr"
    # Persisted to the draft, not main.tex.
    assert r"\newcommand{\cvlang}{fr}" in _draft_path(config).read_text(encoding="utf-8")


def test_set_studio_language_rejects_unknown(tmp_path):
    config = _make_config(tmp_path)
    _write_main(config)
    result = set_studio_language(config, "de")
    assert result["ok"] is False
    assert result["reason"] == "bad_language"


# --- section reorder / swap ----------------------------------------------


def test_reorder_sections_moves_blocks_into_requested_order():
    # Act: request skills before education.
    reordered = reorder_sections(_TEMPLATE, ["sectskills", "sectedu", "sectexp"])

    # Assert: skills now precedes education in the body.
    assert reordered.index(r"\section{\sectskills}") < reordered.index(r"\section{\sectedu}")


def test_swap_studio_sections_swaps_two_named_sections(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    _write_main(config)

    # Act: swap by human labels (display names resolve back to tokens).
    result = swap_studio_sections(config, "Education", "Technical Skills")

    # Assert
    assert result["ok"] is True
    body = result["text"]
    assert body.index(r"\section{\sectskills}") < body.index(r"\section{\sectedu}")


def test_swap_studio_sections_reports_missing_section(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    _write_main(config)

    # Act
    result = swap_studio_sections(config, "Education", "DoesNotExist")

    # Assert
    assert result["ok"] is False
    assert result["reason"] == "section_not_found"


# --- ATS keyword radar ----------------------------------------------------


def test_ats_keyword_radar_reports_coverage_and_missing(tmp_path):
    from job_agent.cv_studio import ats_keyword_radar

    config = _make_config(tmp_path)
    text = "Skilled in Python and SQL with Pandas."

    # Act
    radar = ats_keyword_radar(config, text, role="data_analyst")

    # Assert: present keywords detected, coverage is a percentage.
    assert "Python" in radar["present"]
    assert "SQL" in radar["present"]
    assert "Tableau" in radar["missing"]
    assert 0 <= radar["coverage"] <= 100
