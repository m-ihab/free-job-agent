"""Behavioural tests for CV Studio asset CRUD, icon packs, and project ops.

GitHub HTTP is never called: import_github_project reads only the local
master_cv.json. Photo replacement uses an in-memory base64 blob.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path


from job_agent.config import AppConfig
from job_agent.cv_studio_assets import (
    ICON_PACKS,
    apply_icon_pack,
    list_assets,
    read_asset,
    remove_photo,
    replace_photo,
    write_asset,
)
from job_agent.cv_studio_projects import import_github_project, save_project


def _make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    data_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir)


def _seed_master_cv(config: AppConfig, projects: list[dict]) -> Path:
    path = Path(config.profiles_dir) / "master_cv.json"
    path.write_text(json.dumps({"contact": {"name": "X", "email": "x@y.z"}, "projects": projects}), encoding="utf-8")
    return path


def test_remove_photo_comments_bare_photo_line(tmp_path):
    # Regression: the moderncv default form ``\photo{me.jpg}`` (no [size]
    # options) must be commented out, not just the ``\photo[..]{..}`` form.
    config = _make_config(tmp_path)
    main = Path(config.profiles_dir) / "main.tex"
    main.write_text("\\photo{me.jpg}\n\\name{Jane}{Doe}\n", encoding="utf-8")
    (Path(config.profiles_dir) / "me.jpg").write_bytes(b"\xff\xd8\xff")

    result = remove_photo(config)

    assert result["ok"] is True
    assert "% \\photo{me.jpg}" in main.read_text(encoding="utf-8")
    assert not (Path(config.profiles_dir) / "me.jpg").exists()


def test_remove_photo_still_comments_sized_photo_line(tmp_path):
    config = _make_config(tmp_path)
    main = Path(config.profiles_dir) / "main.tex"
    main.write_text("\\photo[64pt]{me.jpg}\n", encoding="utf-8")

    remove_photo(config)

    assert main.read_text(encoding="utf-8").startswith("% \\photo[64pt]{me.jpg}")


# --- asset listing / read / write ----------------------------------------


def test_list_assets_returns_known_text_and_image_files(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    (Path(config.profiles_dir) / "main.tex").write_text("x", encoding="utf-8")
    (Path(config.profiles_dir) / "me.jpg").write_bytes(b"\xff\xd8\xff")
    (Path(config.profiles_dir) / "ignore.exe").write_bytes(b"MZ")

    # Act
    assets = list_assets(config)
    names = {a["name"]: a["kind"] for a in assets}

    # Assert
    assert names.get("main.tex") == "text"
    assert names.get("me.jpg") == "image"
    assert "ignore.exe" not in names


def test_read_asset_returns_text_content(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    (Path(config.profiles_dir) / "notes.txt").write_text("hello", encoding="utf-8")

    # Act
    result = read_asset(config, "notes.txt")

    # Assert
    assert result["ok"] is True
    assert result["kind"] == "text"
    assert result["text"] == "hello"


def test_read_asset_missing_returns_not_found(tmp_path):
    config = _make_config(tmp_path)
    result = read_asset(config, "ghost.txt")
    assert result == {"ok": False, "reason": "not_found"}


def test_write_asset_creates_backup_of_previous_content(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    target = Path(config.profiles_dir) / "main.tex"
    target.write_text("v1", encoding="utf-8")

    # Act
    result = write_asset(config, "main.tex", "v2")

    # Assert
    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "v2"
    assert (Path(config.profiles_dir) / "main.tex.bak").read_text(encoding="utf-8") == "v1"


def test_write_asset_rejects_binary_suffix(tmp_path):
    config = _make_config(tmp_path)
    (Path(config.profiles_dir) / "me.jpg").write_bytes(b"\xff")
    result = write_asset(config, "me.jpg", "not allowed")
    assert result == {"ok": False, "reason": "binary_asset"}


def test_asset_path_traversal_is_sandboxed(tmp_path):
    # Arrange: try to read outside the profiles dir.
    config = _make_config(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")

    # Act: traversal name is reduced to its basename, so it stays in profiles/.
    result = read_asset(config, "../secret.txt")

    # Assert: the outside file is NOT read (treated as missing inside profiles/).
    assert result["ok"] is False


# --- photo replacement ----------------------------------------------------


def test_replace_photo_writes_decoded_bytes(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    raw = b"\x89PNG\r\n\x1a\n"
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode()

    # Act
    result = replace_photo(config, "me.png", data_url)

    # Assert
    assert result["ok"] is True
    assert (Path(config.profiles_dir) / "me.png").read_bytes() == raw


def test_replace_photo_rejects_invalid_base64(tmp_path):
    config = _make_config(tmp_path)
    result = replace_photo(config, "me.jpg", "!!!not base64!!!")
    assert result == {"ok": False, "reason": "invalid_base64"}


# --- icon packs -----------------------------------------------------------


def test_apply_icon_pack_injects_block_and_backs_up_main(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    main = Path(config.profiles_dir) / "main.tex"
    main.write_text(r"\begin{document}\end{document}", encoding="utf-8")

    # Act
    result = apply_icon_pack(config, "fontawesome")

    # Assert: pack block injected before the document, backup written.
    assert result["ok"] is True
    assert "BEGIN CV-STUDIO ICON PACK" in main.read_text(encoding="utf-8")
    assert "fontawesome5" in main.read_text(encoding="utf-8")
    assert (Path(config.profiles_dir) / "main.tex.bak").exists()


def test_apply_icon_pack_rejects_unknown_pack(tmp_path):
    config = _make_config(tmp_path)
    (Path(config.profiles_dir) / "main.tex").write_text(r"\begin{document}\end{document}", encoding="utf-8")
    result = apply_icon_pack(config, "does-not-exist")
    assert result == {"ok": False, "reason": "unknown_pack"}


def test_icon_pack_registry_has_expected_keys():
    assert set(ICON_PACKS) >= {"moderncv", "fontawesome", "academicons"}


# --- project save / import ------------------------------------------------


def test_save_project_adds_and_promotes_to_top(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    _seed_master_cv(config, [{"name": "Old Project", "description": "d"}])

    # Act
    result = save_project(
        config,
        {"name": "New ML Service", "description": "FastAPI model service", "technologies": ["Python", "Docker"]},
        promote=True,
    )

    # Assert
    assert result["ok"] is True
    assert result["action"] == "added"
    master = json.loads((Path(config.profiles_dir) / "master_cv.json").read_text(encoding="utf-8"))
    assert master["projects"][0]["name"] == "New ML Service"


def test_save_project_requires_name(tmp_path):
    config = _make_config(tmp_path)
    _seed_master_cv(config, [])
    result = save_project(config, {"description": "no name"})
    assert result == {"ok": False, "reason": "name_required"}


def test_save_project_updates_existing_in_place(tmp_path):
    # Arrange
    config = _make_config(tmp_path)
    _seed_master_cv(config, [{"name": "RAG Demo", "description": "old"}])

    # Act
    result = save_project(config, {"name": "RAG Demo", "description": "new description"}, promote=False)

    # Assert
    assert result["action"] == "updated"
    master = json.loads((Path(config.profiles_dir) / "master_cv.json").read_text(encoding="utf-8"))
    rag = next(p for p in master["projects"] if p["name"] == "RAG Demo")
    assert rag["description"] == "new description"


def test_import_github_project_promotes_named_project(tmp_path):
    # Arrange: master_cv has two local projects; main.tex required by the guard.
    config = _make_config(tmp_path)
    _seed_master_cv(config, [
        {"name": "First", "description": "a"},
        {"name": "Target Project", "description": "b", "technologies": ["Python"]},
    ])
    (Path(config.profiles_dir) / "main.tex").write_text(r"\begin{document}\end{document}", encoding="utf-8")

    # Act
    result = import_github_project(config, "Target Project")

    # Assert: chosen project promoted to the front of master_cv.json::projects.
    assert result["ok"] is True
    assert result["promoted"] == "Target Project"
    master = json.loads((Path(config.profiles_dir) / "master_cv.json").read_text(encoding="utf-8"))
    assert master["projects"][0]["name"] == "Target Project"


def test_import_github_project_missing_project_returns_reason(tmp_path):
    config = _make_config(tmp_path)
    _seed_master_cv(config, [{"name": "Only"}])
    (Path(config.profiles_dir) / "main.tex").write_text(r"\begin{document}\end{document}", encoding="utf-8")
    result = import_github_project(config, "Nonexistent")
    assert result == {"ok": False, "reason": "project_not_found"}
