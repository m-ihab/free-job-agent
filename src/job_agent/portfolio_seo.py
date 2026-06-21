"""Portfolio SEO artifacts: robots.txt and sitemap.xml."""
from __future__ import annotations

import html

from job_agent.portfolio_render_core import PortfolioConfig


def _render_robots(cfg: PortfolioConfig) -> str:
    # Default to Disallow: the portfolio is a private local asset unless the
    # user opts into public_mode. Avoids accidental indexing if the port leaks.
    rule = "Allow: /" if cfg.public_mode else "Disallow: /"
    base = f"User-agent: *\n{rule}\n"
    if cfg.site_url:
        base += f"\nSitemap: {cfg.site_url.rstrip('/')}/sitemap.xml\n"
    return base


def _render_sitemap(cfg: PortfolioConfig) -> str:
    if not cfg.site_url:
        return ""
    url = cfg.site_url.rstrip("/")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{html.escape(url)}/</loc></url>\n"
        "</urlset>\n"
    )
