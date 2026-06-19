"""Regression tests for the Portfolio Builder v2 capabilities."""
from __future__ import annotations

from pathlib import Path


from job_agent.config import AppConfig
from job_agent.portfolio_builder import (
    FONTS,
    HERO_LAYOUTS,
    OPTIONAL_SECTIONS,
    THEMES,
    PortfolioConfig,
    generate_portfolio,
    portfolio_state,
    publish_guide,
)


EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _setup(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / ".job_agent"
    profiles_dir = data_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    for name in ("candidate_profile.json", "master_cv.json", "master_qa_profile.json"):
        (profiles_dir / name).write_text((EXAMPLES_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    return AppConfig(
        data_dir=data_dir,
        profiles_dir=profiles_dir,
        outputs_dir=data_dir / "outputs",
        db_path=data_dir / "jobs.db",
    )


def test_portfolio_has_at_least_ten_themes_and_fonts():
    assert len(THEMES) >= 10
    assert len(FONTS) >= 10
    assert "split" in HERO_LAYOUTS and "centered" in HERO_LAYOUTS and "cinematic" in HERO_LAYOUTS


def test_portfolio_state_exposes_full_catalogue(tmp_path):
    config = _setup(tmp_path)
    state = portfolio_state(config)
    assert len(state["themes"]) == len(THEMES)
    assert len(state["fonts"]) == len(FONTS)
    assert len(state["layouts"]) == len(HERO_LAYOUTS)
    assert state["optional_sections"] == list(OPTIONAL_SECTIONS)


def test_portfolio_renders_each_theme(tmp_path):
    config = _setup(tmp_path)
    for theme in THEMES:
        result = generate_portfolio(config, theme=theme, font="inter", layout="split")
        assert result["ok"] is True
        assert "</html>" in result["html"]
        # CSS must include the theme variable block.
        assert "--accent:" in result["css"]


def test_portfolio_each_layout_changes_hero(tmp_path):
    config = _setup(tmp_path)
    htmls = {}
    for layout in HERO_LAYOUTS:
        result = generate_portfolio(config, theme="signal", font="inter", layout=layout)
        htmls[layout] = result["html"]
    assert 'hero-grid split' in htmls["split"]
    assert 'hero-grid centered' in htmls["centered"]
    assert 'hero-grid cinematic' in htmls["cinematic"]


def test_portfolio_custom_accent_applied(tmp_path):
    config = _setup(tmp_path)
    result = generate_portfolio(config, theme="signal", custom_accent="#abcdef")
    assert "#abcdef" in result["css"]


def test_portfolio_invalid_accent_ignored(tmp_path):
    config = _setup(tmp_path)
    result = generate_portfolio(config, theme="signal", custom_accent="not-a-hex")
    # Falls back to the theme's accent (not the rejected value).
    assert "not-a-hex" not in result["css"]


def test_portfolio_optional_section_renders_when_enabled(tmp_path):
    config = _setup(tmp_path)
    result = generate_portfolio(config, sections={"awards": True, "open_source": True})
    assert "id=\"awards\"" in result["html"]
    assert "id=\"open-source\"" in result["html"]


def test_portfolio_optional_section_hidden_when_disabled(tmp_path):
    config = _setup(tmp_path)
    result = generate_portfolio(config, sections={"awards": False, "open_source": False})
    assert "id=\"awards\"" not in result["html"]
    assert "id=\"open-source\"" not in result["html"]


def test_portfolio_dark_toggle_can_be_disabled(tmp_path):
    config = _setup(tmp_path)
    on = generate_portfolio(config, enable_dark_toggle=True)
    off = generate_portfolio(config, enable_dark_toggle=False)
    assert "[data-theme=\"dark\"]" in on["css"]
    assert "data-toggle-theme" in on["html"]
    assert "[data-theme=\"dark\"]" not in off["css"]


def test_portfolio_animations_can_be_disabled(tmp_path):
    config = _setup(tmp_path)
    on = generate_portfolio(config, enable_animations=True)
    off = generate_portfolio(config, enable_animations=False)
    assert "[data-reveal]" in on["css"]
    assert "[data-reveal]" not in off["css"]


def test_portfolio_seo_meta_present(tmp_path):
    config = _setup(tmp_path)
    result = generate_portfolio(config, site_url="https://example.com/portfolio")
    out_dir = Path(config.data_dir) / "portfolio"
    assert "og:title" in result["html"]
    assert "<link rel=\"canonical\"" in result["html"]
    assert (out_dir / "robots.txt").exists()
    assert (out_dir / "sitemap.xml").exists()


def test_publish_guide_lists_multiple_hosts(tmp_path):
    config = _setup(tmp_path)
    result = publish_guide(config)
    assert result["ok"]
    assert "github_pages" in result["hosts"]
    assert "netlify" in result["hosts"]
    assert "vercel" in result["hosts"]


def test_portfolio_config_normalizes_invalid_values():
    cfg = PortfolioConfig(theme="nope", font="???", layout="x", custom_accent="bad").normalized()
    assert cfg.theme == "signal"
    assert cfg.font == "inter"
    assert cfg.layout == "split"
    assert cfg.custom_accent == ""
    for key in OPTIONAL_SECTIONS:
        assert key in cfg.sections
