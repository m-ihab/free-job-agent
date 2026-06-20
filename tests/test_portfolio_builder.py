"""Behavioural tests for the portfolio site builder + renderer.

Builds into a temp data dir. GitHub HTTP import is mocked. Asserts that the
rendered HTML/CSS contain the expected tokens for the chosen theme / font /
layout / sections and that SEO artifacts (robots/sitemap) are correct.
"""
from __future__ import annotations

import json
from pathlib import Path


import job_agent.portfolio_builder as pb
from job_agent.config import AppConfig
from job_agent.portfolio_builder import (
    export_portfolio_zip,
    fetch_github_repos,
    generate_portfolio,
    generate_tagline,
    import_repos_to_portfolio,
    portfolio_state,
    portfolio_suggestions,
    publish_guide,
    read_portfolio,
    save_portfolio,
)
from job_agent.portfolio_render import (
    FONTS,
    THEMES,
    PortfolioConfig,
    _render_css,
    _render_robots,
    _render_sitemap,
    _section_card_html,
)


def _make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    data_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    examples = Path(__file__).parent.parent / "examples"
    for name in ("candidate_profile.json", "master_cv.json", "master_qa_profile.json"):
        (profiles_dir / name).write_text((examples / name).read_text(encoding="utf-8"), encoding="utf-8")
    return AppConfig(data_dir=data_dir, profiles_dir=profiles_dir)


# --- PortfolioConfig normalisation ---------------------------------------


def test_portfolio_config_normalizes_unknown_theme_font_layout():
    cfg = PortfolioConfig(theme="nope", font="nope", layout="nope", custom_accent="bad").normalized()
    assert cfg.theme == "signal"
    assert cfg.font == "inter"
    assert cfg.layout == "split"
    assert cfg.custom_accent == ""  # invalid hex dropped


def test_portfolio_config_keeps_valid_custom_accent():
    cfg = PortfolioConfig(custom_accent="#abcdef").normalized()
    assert cfg.custom_accent == "#abcdef"
    # all optional sections default to False
    assert all(v is False for v in cfg.sections.values())


# --- CSS rendering --------------------------------------------------------


def test_render_css_uses_selected_theme_palette_and_font():
    cfg = PortfolioConfig(theme="midnight", font="mono").normalized()
    css = _render_css(cfg)
    assert THEMES["midnight"]["bg"] in css
    assert THEMES["midnight"]["accent"] in css
    assert FONTS["mono"]["stack"] in css


def test_render_css_custom_accent_overrides_theme_accent():
    cfg = PortfolioConfig(theme="signal", custom_accent="#123456").normalized()
    css = _render_css(cfg)
    assert "--accent: #123456;" in css


def test_render_css_omits_animation_block_when_disabled():
    enabled = _render_css(PortfolioConfig(enable_animations=True).normalized())
    disabled = _render_css(PortfolioConfig(enable_animations=False).normalized())
    assert "[data-reveal].in" in enabled
    assert "[data-reveal].in" not in disabled


# --- SEO: robots + sitemap ------------------------------------------------


def test_render_robots_without_site_url_has_no_sitemap_line():
    robots = _render_robots(PortfolioConfig().normalized())
    assert "User-agent: *" in robots
    assert "Sitemap:" not in robots


def test_render_robots_and_sitemap_with_site_url():
    cfg = PortfolioConfig(site_url="https://me.example.com/").normalized()
    robots = _render_robots(cfg)
    sitemap = _render_sitemap(cfg)
    assert "Sitemap: https://me.example.com/sitemap.xml" in robots
    assert "<loc>https://me.example.com/</loc>" in sitemap


def test_render_sitemap_empty_without_site_url():
    assert _render_sitemap(PortfolioConfig().normalized()) == ""


# --- section card html ----------------------------------------------------


def test_section_card_html_empty_placeholder():
    assert "Empty section" in _section_card_html([], 0)


def test_section_card_html_escapes_and_renders_items():
    html = _section_card_html([{"title": "A&B", "detail": "<x>"}], 0)
    assert "A&amp;B" in html
    assert "&lt;x&gt;" in html
    assert "data-reveal" in html


# --- generate_portfolio (full build into temp dir) -----------------------


def test_generate_portfolio_writes_html_css_and_robots(tmp_path):
    # Arrange
    config = _make_config(tmp_path)

    # Act: choose a non-default theme + an enabled optional section.
    result = generate_portfolio(config, theme="neon", layout="centered", sections={"awards": True})

    # Assert: artifacts written.
    out = Path(result["path"])
    assert (out / "index.html").exists()
    assert (out / "style.css").exists()
    assert (out / "robots.txt").exists()
    html = (out / "index.html").read_text(encoding="utf-8")
    # The centered layout class and awards section anchor appear.
    assert "hero-grid centered" in html
    assert 'id="awards"' in html
    # Candidate name from the example profile is present.
    assert "Candidate Data AI Paris" in html


def test_generate_portfolio_no_sitemap_file_without_site_url(tmp_path):
    config = _make_config(tmp_path)
    result = generate_portfolio(config)
    out = Path(result["path"])
    assert not (out / "sitemap.xml").exists()


def test_generate_portfolio_writes_sitemap_when_site_url_set(tmp_path):
    config = _make_config(tmp_path)
    result = generate_portfolio(config, site_url="https://me.example.com")
    out = Path(result["path"])
    assert (out / "sitemap.xml").exists()


def test_portfolio_state_reports_themes_fonts_layouts(tmp_path):
    config = _make_config(tmp_path)
    state = portfolio_state(config)
    assert state["ok"] is True
    theme_keys = {t["key"] for t in state["themes"]}
    assert "signal" in theme_keys and "midnight" in theme_keys
    assert any(f["key"] == "inter" for f in state["fonts"])


# --- GitHub import (HTTP mocked) -----------------------------------------


def test_fetch_github_repos_returns_empty_without_requests(monkeypatch):
    # Arrange: simulate requests being unavailable.
    monkeypatch.setattr(pb, "requests", None)

    # Act / Assert
    assert fetch_github_repos("someone") == []


def test_import_repos_to_portfolio_promotes_fetched_repo(tmp_path, monkeypatch):
    # Arrange: stub fetch_github_repos so no HTTP happens.
    config = _make_config(tmp_path)
    monkeypatch.setattr(pb, "fetch_github_repos", lambda handle, **k: [
        {"name": "cool-ml-repo", "description": "An ML repo", "url": "https://github.com/u/cool-ml-repo",
         "language": "Python", "topics": ["ml"], "stars": 3, "updated_at": ""},
    ])

    # Act
    result = import_repos_to_portfolio(config, ["cool-ml-repo"], handle="u")

    # Assert: the repo becomes the first project, humanised.
    assert result["ok"] is True
    assert "cool-ml-repo" in result["added"]
    master = json.loads((Path(config.profiles_dir) / "master_cv.json").read_text(encoding="utf-8"))
    assert master["projects"][0]["name"] == "Cool Ml Repo"
    assert "Python" in master["projects"][0]["technologies"]


# --- read / save / export / publish / AI fallbacks -----------------------


def test_read_portfolio_generates_when_missing(tmp_path):
    config = _make_config(tmp_path)
    state = read_portfolio(config)
    assert state["exists"] is True
    assert "<!doctype html>" in state["html"].lower()


def test_save_portfolio_writes_and_backs_up(tmp_path):
    # Arrange: generate once so originals exist to back up.
    config = _make_config(tmp_path)
    generate_portfolio(config)

    # Act
    result = save_portfolio(config, "<html>new</html>", "body{}")

    # Assert
    out = Path(result["path"])
    assert (out / "index.html").read_text(encoding="utf-8") == "<html>new</html>"
    assert (out / "index.html.bak").exists()


def test_export_portfolio_zip_contains_site_files(tmp_path):
    config = _make_config(tmp_path)
    generate_portfolio(config)
    zip_path = export_portfolio_zip(config)
    import zipfile

    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert "index.html" in names
    assert "style.css" in names


def test_publish_guide_writes_markdown_with_hosts(tmp_path):
    config = _make_config(tmp_path)
    result = publish_guide(config)
    assert result["ok"] is True
    guide = Path(result["path"])
    assert guide.exists()
    assert "GitHub Pages" in guide.read_text(encoding="utf-8")


def test_portfolio_suggestions_falls_back_to_deterministic(tmp_path, monkeypatch):
    # Arrange: force AI unavailable.
    monkeypatch.setattr(pb, "_ai_is_available", None)
    config = _make_config(tmp_path)

    # Act
    result = portfolio_suggestions(config)

    # Assert
    assert result["available"] is False
    assert len(result["suggestions"]) >= 3


def test_generate_tagline_falls_back_when_ai_unavailable(tmp_path, monkeypatch):
    # Arrange
    monkeypatch.setattr(pb, "_ai_is_available", None)
    config = _make_config(tmp_path)

    # Act
    result = generate_tagline(config)

    # Assert: deterministic fallback tagline.
    assert result["available"] is False
    assert result["tagline"]


def test_import_repos_missing_master_cv_returns_reason(tmp_path, monkeypatch):
    # Arrange: profiles dir without master_cv.json.
    data_dir = tmp_path / "data"
    profiles_dir = tmp_path / "profiles"
    data_dir.mkdir()
    profiles_dir.mkdir()
    config = AppConfig(data_dir=data_dir, profiles_dir=profiles_dir)

    # Act
    result = import_repos_to_portfolio(config, ["x"], handle="u")

    # Assert
    assert result == {"ok": False, "reason": "no_master_cv"}


# --- section ordering -----------------------------------------------------


def test_section_order_normalizes_drops_unknown_and_appends_missing():
    from job_agent.portfolio_render import PortfolioConfig, REORDERABLE_SECTIONS

    cfg = PortfolioConfig(section_order=["experience", "skills", "bogus", "experience"]).normalized()
    # de-duped, unknown dropped, missing appended in default order
    assert cfg.section_order[:2] == ["experience", "skills"]
    assert set(cfg.section_order) == set(REORDERABLE_SECTIONS)
    assert len(cfg.section_order) == len(REORDERABLE_SECTIONS)


def test_section_order_default_when_unset():
    from job_agent.portfolio_render import PortfolioConfig, REORDERABLE_SECTIONS

    cfg = PortfolioConfig().normalized()
    assert cfg.section_order == list(REORDERABLE_SECTIONS)


def test_generate_portfolio_respects_section_order(tmp_path):
    config = _make_config(tmp_path)
    result = generate_portfolio(config, section_order=["experience", "skills", "projects", "education"])
    html_text = result["html"]
    assert html_text.index('id="experience"') < html_text.index('id="skills"')
