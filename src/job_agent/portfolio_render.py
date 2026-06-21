"""Portfolio rendering layer — public facade.

The implementation is split into cohesive modules to keep each focused:
  * :mod:`job_agent.portfolio_render_core` — themes, fonts, ``PortfolioConfig``, helpers
  * :mod:`job_agent.portfolio_css` — CSS renderer
  * :mod:`job_agent.portfolio_html` — HTML renderer
  * :mod:`job_agent.portfolio_seo` — robots.txt / sitemap.xml

This module re-exports the public surface so existing imports
(``from job_agent.portfolio_render import ...``) keep working. The orchestration
API (generate / read / save / export / publish / AI / GitHub import) lives in
:mod:`job_agent.portfolio_builder`, which imports these symbols back. Nothing
here imports ``portfolio_builder``, so there is no import cycle.
"""
from __future__ import annotations

from job_agent.portfolio_css import _render_css
from job_agent.portfolio_html import _render_html, _section_card_html, _site_url_meta
from job_agent.portfolio_render_core import (
    FONTS,
    HERO_LAYOUTS,
    OPTIONAL_SECTIONS,
    REORDERABLE_SECTIONS,
    THEMES,
    PortfolioConfig,
    _as_dict,
    _listify,
    _nonempty,
    _photo_asset,
    _portfolio_dir,
)
from job_agent.portfolio_seo import _render_robots, _render_sitemap

__all__ = [
    "FONTS",
    "HERO_LAYOUTS",
    "OPTIONAL_SECTIONS",
    "REORDERABLE_SECTIONS",
    "THEMES",
    "PortfolioConfig",
    "_as_dict",
    "_listify",
    "_nonempty",
    "_photo_asset",
    "_portfolio_dir",
    "_render_css",
    "_render_html",
    "_render_robots",
    "_render_sitemap",
    "_section_card_html",
    "_site_url_meta",
]
