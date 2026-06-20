"""Tests for portfolio photo validation and theme precedence.

A 0-byte ``me.jpg`` must not be used as the portrait (falls back to a non-empty
``.bak``), and a chosen theme must not be flattened by an OS dark-mode override.
"""
from __future__ import annotations

from pathlib import Path

from job_agent.config import AppConfig
from job_agent.portfolio_render import THEMES, PortfolioConfig, _photo_asset, _render_css


def _make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    data_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir)


JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 40  # non-empty fake JPEG


def test_photo_asset_skips_empty_and_uses_bak(tmp_path):
    config = _make_config(tmp_path)
    profiles = Path(config.profiles_dir)
    (profiles / "me.jpg").write_bytes(b"")          # the 0-byte corruption
    (profiles / "me.jpg.bak").write_bytes(JPEG_BYTES)  # good backup

    name = _photo_asset(config)

    assert name == "me.jpg"
    # The copied portrait must be the non-empty backup, not the empty primary.
    out = Path(config.data_dir) / "portfolio" / "me.jpg"
    assert out.exists() and out.stat().st_size > 0


def test_photo_asset_returns_empty_when_no_usable_image(tmp_path):
    config = _make_config(tmp_path)
    (Path(config.profiles_dir) / "me.jpg").write_bytes(b"")  # empty, no backup
    assert _photo_asset(config) == ""


def test_photo_asset_uses_nonempty_primary(tmp_path):
    config = _make_config(tmp_path)
    (Path(config.profiles_dir) / "me.jpg").write_bytes(JPEG_BYTES)
    assert _photo_asset(config) == "me.jpg"


def test_render_css_has_no_auto_dark_media_override(tmp_path):
    # No OS auto-dark override (it would flatten distinct themes).
    cfg = PortfolioConfig(theme="signal", enable_dark_toggle=True)
    css = _render_css(cfg)
    assert "prefers-color-scheme: dark" not in css
    # The explicit manual toggle remains available.
    assert 'html[data-theme="dark"]' in css


def test_distinct_themes_render_distinct_palettes(tmp_path):
    names = list(THEMES.keys())[:2]
    css_a = _render_css(PortfolioConfig(theme=names[0]))
    css_b = _render_css(PortfolioConfig(theme=names[1]))
    assert css_a != css_b
