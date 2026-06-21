"""Portfolio CSS renderer: theme variables + base styles + animation block."""
from __future__ import annotations

from job_agent.portfolio_render_core import FONTS, THEMES, PortfolioConfig


def _render_css(cfg: PortfolioConfig) -> str:
    theme = THEMES.get(cfg.theme, THEMES["signal"])
    font = FONTS.get(cfg.font, FONTS["inter"])
    accent = cfg.custom_accent or theme["accent"]
    css_vars = f""":root {{
  --bg: {theme['bg']};
  --ink: {theme['ink']};
  --muted: {theme['muted']};
  --surface: {theme['surface']};
  --accent: {accent};
  --accent-2: {theme['accent2']};
  --font: {font['stack']};
  --radius: 18px;
  --shadow: 0 24px 60px rgba(0,0,0,0.12);
}}
"""
    # The chosen theme palette is authoritative; no automatic
    # ``prefers-color-scheme: dark`` override (it would flatten every theme to one
    # palette in OS dark mode). Dark mode is opt-in via ``html[data-theme="dark"]``.
    dark_block = """
html[data-theme="dark"] {
  --bg: #07111f;
  --ink: #e5edf8;
  --muted: #9fb2ca;
  --surface: #0d1b2d;
}
""" if cfg.enable_dark_toggle else ""
    base = """
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: var(--font);
  background: var(--bg);
  color: var(--ink);
  line-height: 1.65;
  -webkit-font-smoothing: antialiased;
}
a { color: inherit; text-decoration: none; border-bottom: 1px dotted color-mix(in srgb, var(--accent) 50%, transparent); transition: color 0.2s ease, border-color 0.2s ease; }
a:hover { color: var(--accent); border-bottom-color: var(--accent); }
.wrap { width: min(1200px, calc(100% - 32px)); margin: 0 auto; }
header.site { position: sticky; top: 0; z-index: 10; backdrop-filter: blur(10px); background: color-mix(in srgb, var(--bg) 75%, transparent); border-bottom: 1px solid color-mix(in srgb, var(--muted) 16%, transparent); }
header.site .wrap { display: flex; justify-content: space-between; align-items: center; padding: 14px 0; }
header.site nav a { margin-left: 18px; font-weight: 600; font-size: 0.92rem; border-bottom: none; }
header.site nav a:hover { color: var(--accent); }
.brand { font-weight: 800; letter-spacing: -0.01em; }
.toggle-theme { border: 1px solid color-mix(in srgb, var(--muted) 30%, transparent); background: transparent; color: inherit; padding: 6px 12px; border-radius: 999px; font-size: 0.8rem; cursor: pointer; margin-left: 12px; }
.toggle-theme:hover { border-color: var(--accent); color: var(--accent); }
.hero { padding: 72px 0 48px; }
.hero-grid { display: grid; gap: 42px; align-items: center; }
.hero-grid.split { grid-template-columns: 1.3fr 0.7fr; }
.hero-grid.centered { grid-template-columns: 1fr; text-align: center; }
.hero-grid.centered .actions { justify-content: center; }
.hero-grid.cinematic { grid-template-columns: 1fr; text-align: left; padding: 92px 0 60px; }
.hero-grid.cinematic .lead { max-width: 70ch; }
.eyebrow { color: var(--accent); text-transform: uppercase; font-size: 0.78rem; font-weight: 800; letter-spacing: 0.12em; }
h1.headline { font-size: clamp(2.4rem, 7vw, 5.6rem); line-height: 0.98; margin: 12px 0 20px; letter-spacing: -0.02em; font-weight: 800; }
h1 .accent { color: var(--accent); }
.lead { color: var(--muted); font-size: clamp(1.05rem, 1.8vw, 1.35rem); max-width: 64ch; }
.portrait { width: min(360px, 72vw); aspect-ratio: 1; object-fit: cover; border-radius: 28px; border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent); box-shadow: var(--shadow); }
.actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }
.btn { border: 1px solid color-mix(in srgb, var(--accent) 50%, transparent); border-radius: 999px; padding: 12px 18px; font-weight: 700; transition: transform 0.15s ease, background 0.18s ease, color 0.18s ease; }
.btn:hover { transform: translateY(-1px); }
.btn.primary { background: var(--accent); color: white; border-color: var(--accent); }
.btn.primary:hover { background: color-mix(in srgb, var(--accent) 80%, black); }
.section { padding: 64px 0; border-top: 1px solid color-mix(in srgb, var(--muted) 16%, transparent); }
.section h2 { font-size: clamp(1.7rem, 3vw, 2.6rem); margin: 0 0 24px; letter-spacing: -0.01em; }
.section .lead { margin-bottom: 28px; }
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; }
.grid.cards-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.card { background: var(--surface); border: 1px solid color-mix(in srgb, var(--muted) 16%, transparent); border-radius: var(--radius); padding: 22px; box-shadow: 0 12px 36px rgba(0,0,0,0.06); }
.card h3 { margin: 0 0 8px; font-size: 1.15rem; }
.card .muted { font-size: 0.95rem; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.chip { padding: 5px 11px; border-radius: 999px; background: color-mix(in srgb, var(--accent) 14%, transparent); color: var(--ink); font-weight: 600; font-size: 0.8rem; }
.timeline { display: grid; gap: 18px; }
.job { display: grid; grid-template-columns: 200px 1fr; gap: 18px; align-items: start; padding: 18px; background: var(--surface); border: 1px solid color-mix(in srgb, var(--muted) 16%, transparent); border-radius: var(--radius); }
.job ul { margin: 6px 0 0 18px; padding: 0; }
.job ul li { margin-bottom: 4px; }
.kv { display: grid; grid-template-columns: 130px 1fr; gap: 14px 18px; font-size: 0.95rem; }
.kv dt { color: var(--muted); font-weight: 600; }
footer { padding: 36px 0 56px; color: var(--muted); border-top: 1px solid color-mix(in srgb, var(--muted) 16%, transparent); }
footer .wrap { display: flex; flex-wrap: wrap; gap: 16px; justify-content: space-between; align-items: center; }
.print-hint { display: none; }
@media print {
  header.site, .toggle-theme, .actions, .print-hint { display: none; }
  body { background: white; color: black; }
  .section, .card, .job { border: none; box-shadow: none; padding: 0 0 18px; }
}
@media (max-width: 820px) {
  .hero-grid.split, .grid, .grid.cards-2, .job { grid-template-columns: 1fr; }
}
"""
    animations = """
[data-reveal] { opacity: 0; transform: translateY(18px); transition: opacity 0.6s ease, transform 0.6s ease; }
[data-reveal].in { opacity: 1; transform: translateY(0); }
""" if cfg.enable_animations else ""
    return css_vars + dark_block + base + animations
