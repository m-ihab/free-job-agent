"""Portfolio rendering layer: themes, fonts, the ``PortfolioConfig`` dataclass,
and the HTML / CSS / robots / sitemap renderers.

This module holds the presentation concerns for the Portfolio Builder. The
public orchestration API (generate / read / save / export / publish / AI /
GitHub import) lives in :mod:`job_agent.portfolio_builder`, which imports these
symbols back. Nothing here imports ``portfolio_builder``, so there is no import
cycle.
"""
from __future__ import annotations

import html
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from job_agent.config import AppConfig
from job_agent.validators import load_profile_bundle


# ---------------------------------------------------------------------------
# Themes — eleven curated palettes, all CSS-variable driven.
# ---------------------------------------------------------------------------
THEMES: dict[str, dict[str, str]] = {
    "signal": {
        "label": "Signal", "preset": "light",
        "bg": "#f8fafc", "ink": "#0f172a", "muted": "#475569",
        "surface": "#ffffff", "accent": "#2563eb", "accent2": "#14b8a6",
    },
    "midnight": {
        "label": "Midnight Lab", "preset": "dark",
        "bg": "#07111f", "ink": "#e5edf8", "muted": "#9fb2ca",
        "surface": "#0d1b2d", "accent": "#38bdf8", "accent2": "#a78bfa",
    },
    "editorial": {
        "label": "Editorial", "preset": "light",
        "bg": "#fbfaf8", "ink": "#171717", "muted": "#5f5b55",
        "surface": "#ffffff", "accent": "#b45309", "accent2": "#0f766e",
    },
    "terminal": {
        "label": "Terminal", "preset": "dark",
        "bg": "#07130c", "ink": "#e8ffe8", "muted": "#9ac99a",
        "surface": "#0d1d13", "accent": "#22c55e", "accent2": "#facc15",
    },
    "japandi": {
        "label": "Japandi", "preset": "light",
        "bg": "#f3efe9", "ink": "#1f1b16", "muted": "#6c5f50",
        "surface": "#fbf8f2", "accent": "#7c4a2a", "accent2": "#3f5d52",
    },
    "neon": {
        "label": "Neon Grid", "preset": "dark",
        "bg": "#0a0820", "ink": "#f5f3ff", "muted": "#b8b3df",
        "surface": "#161336", "accent": "#ec4899", "accent2": "#22d3ee",
    },
    "brutalist": {
        "label": "Brutalist", "preset": "light",
        "bg": "#fef9c3", "ink": "#0b0b0b", "muted": "#4b4b4b",
        "surface": "#ffffff", "accent": "#000000", "accent2": "#dc2626",
    },
    "glass": {
        "label": "Glassmorphism", "preset": "dark",
        "bg": "#0e1a2f", "ink": "#f0f7ff", "muted": "#a0b5d5",
        "surface": "rgba(255, 255, 255, 0.06)", "accent": "#60a5fa", "accent2": "#f472b6",
    },
    "lab": {
        "label": "Research Lab", "preset": "light",
        "bg": "#f0f4f8", "ink": "#0c1a2b", "muted": "#4b6584",
        "surface": "#ffffff", "accent": "#0ea5e9", "accent2": "#6366f1",
    },
    "magazine": {
        "label": "Magazine", "preset": "light",
        "bg": "#ffffff", "ink": "#111111", "muted": "#6b7280",
        "surface": "#f9fafb", "accent": "#e11d48", "accent2": "#1d4ed8",
    },
    "gradient": {
        "label": "Gradient Pop", "preset": "light",
        "bg": "linear-gradient(135deg, #fef3c7 0%, #fde68a 25%, #fca5a5 70%, #fbcfe8 100%)",
        "ink": "#1f2937", "muted": "#4b5563",
        "surface": "rgba(255, 255, 255, 0.85)", "accent": "#7c3aed", "accent2": "#0ea5e9",
    },
}


# ---------------------------------------------------------------------------
# Fonts — 12 stacks with optional Google Fonts <link> (loaded only when chosen).
# ---------------------------------------------------------------------------
FONTS: dict[str, dict[str, str]] = {
    "inter": {"label": "Inter", "stack": "Inter, ui-sans-serif, system-ui, sans-serif", "google": "Inter:wght@400;600;700;800"},
    "plex": {"label": "IBM Plex Sans", "stack": "'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif", "google": "IBM+Plex+Sans:wght@400;500;700"},
    "space": {"label": "Space Grotesk", "stack": "'Space Grotesk', ui-sans-serif, system-ui, sans-serif", "google": "Space+Grotesk:wght@400;500;700"},
    "manrope": {"label": "Manrope", "stack": "Manrope, ui-sans-serif, sans-serif", "google": "Manrope:wght@400;500;700;800"},
    "sora": {"label": "Sora", "stack": "Sora, ui-sans-serif, sans-serif", "google": "Sora:wght@400;600;800"},
    "jakarta": {"label": "Plus Jakarta Sans", "stack": "'Plus Jakarta Sans', sans-serif", "google": "Plus+Jakarta+Sans:wght@400;600;800"},
    "outfit": {"label": "Outfit", "stack": "Outfit, sans-serif", "google": "Outfit:wght@400;600;800"},
    "serif": {"label": "Lora (serif)", "stack": "Lora, ui-serif, Georgia, serif", "google": "Lora:wght@400;500;700"},
    "playfair": {"label": "Playfair Display (display serif)", "stack": "'Playfair Display', ui-serif, Georgia, serif", "google": "Playfair+Display:wght@400;700;900"},
    "mono": {"label": "JetBrains Mono", "stack": "'JetBrains Mono', 'Cascadia Code', ui-monospace, monospace", "google": "JetBrains+Mono:wght@400;500;700"},
    "recursive": {"label": "Recursive (variable)", "stack": "Recursive, ui-sans-serif, sans-serif", "google": "Recursive:slnt,wght,CASL,CRSV,MONO@-15..0,300..1000,0..1,0..1,0..1"},
    "system": {"label": "System UI", "stack": "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", "google": ""},
}


HERO_LAYOUTS = {
    "split": "Split (text + portrait)",
    "centered": "Centered headline (no portrait)",
    "cinematic": "Cinematic (full-bleed gradient cover)",
}


OPTIONAL_SECTIONS = ("testimonials", "open_source", "speaking", "awards", "blog")

# Middle sections the user can reorder (hero is always first, contact always last).
REORDERABLE_SECTIONS = ("skills", "projects", "experience", "education")


@dataclass
class PortfolioConfig:
    theme: str = "signal"
    font: str = "inter"
    layout: str = "split"
    custom_accent: str = ""
    sections: dict[str, bool] = None  # type: ignore[assignment]
    section_order: list[str] = None  # type: ignore[assignment]
    tagline: str = ""
    site_url: str = ""
    site_title_suffix: str = "Portfolio"
    enable_dark_toggle: bool = True
    enable_animations: bool = True

    def normalized(self) -> "PortfolioConfig":
        sections = dict(self.sections or {})
        for key in OPTIONAL_SECTIONS:
            sections.setdefault(key, False)
        if self.theme not in THEMES:
            self.theme = "signal"
        if self.font not in FONTS:
            self.font = "inter"
        if self.layout not in HERO_LAYOUTS:
            self.layout = "split"
        if self.custom_accent and not re.fullmatch(r"#[0-9a-fA-F]{6}", self.custom_accent):
            self.custom_accent = ""
        self.sections = sections
        # Reorderable middle sections (hero stays first, contact last). Keep only
        # valid keys, de-duplicate, then append any missing in their default order.
        seen: list[str] = []
        for key in (self.section_order or []):
            if key in REORDERABLE_SECTIONS and key not in seen:
                seen.append(key)
        for key in REORDERABLE_SECTIONS:
            if key not in seen:
                seen.append(key)
        self.section_order = seen
        return self


def _portfolio_dir(config: AppConfig) -> Path:
    base = Path(config.data_dir or Path.cwd() / ".job_agent") / "portfolio"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _nonempty(path: Path) -> bool:
    """True only if ``path`` exists and is not a 0-byte file."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _photo_asset(config: AppConfig) -> str:
    """Copy a usable portrait into the portfolio dir, returning its filename.

    Validates the source is non-empty before copying (a 0-byte ``me.jpg`` would
    otherwise render as a broken image), and falls back to a non-empty ``.bak``
    sibling when the primary asset is empty.
    """
    profiles = Path(config.profiles_dir or "")
    for name in ("me.jpg", "me.jpeg", "me.png"):
        # Prefer the live asset; fall back to its .bak if the live one is empty.
        for candidate in (profiles / name, profiles / f"{name}.bak"):
            if not _nonempty(candidate):
                continue
            target = _portfolio_dir(config) / name
            try:
                shutil.copyfile(candidate, target)
                return name
            except Exception:
                break  # try the next image name
    return ""


def _as_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model or {})


def _listify(value: Any, limit: int = 12) -> list[str]:
    result: list[str] = []
    for item in value or []:
        if isinstance(item, dict):
            label = item.get("name") or item.get("title") or item.get("label")
        else:
            label = str(item)
        label = str(label or "").strip()
        if label and label not in result:
            result.append(label)
    return result[:limit]


# ---------------------------------------------------------------------------
# CSS rendering — splits into theme variables + base styles + animation block.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# HTML rendering — supports three hero layouts + optional sections.
# ---------------------------------------------------------------------------


def _section_card_html(items: list[dict[str, Any]], reveal_idx: int) -> str:
    if not items:
        return "<p class='muted'>Empty section. Populate via the editor.</p>"
    parts = []
    for idx, item in enumerate(items):
        title = html.escape(str(item.get("title") or item.get("name") or ""))
        detail = html.escape(str(item.get("detail") or item.get("description") or ""))
        meta = html.escape(str(item.get("meta") or item.get("year") or ""))
        small = f'<small class="muted">{meta}</small>' if meta else ""
        parts.append(
            f'<article class="card" data-reveal="{reveal_idx + idx}">'
            f'<h3>{title}</h3>'
            f'<p class="muted">{detail}</p>'
            f'{small}'
            "</article>"
        )
    return "<div class='grid cards-2'>" + "".join(parts) + "</div>"


def _site_url_meta(cfg: PortfolioConfig) -> str:
    if not cfg.site_url:
        return ""
    url = html.escape(cfg.site_url)
    return f'\n  <link rel="canonical" href="{url}" />\n  <meta property="og:url" content="{url}" />'


def _render_html(config: AppConfig, cfg: PortfolioConfig) -> str:
    profile, master_cv, _ = load_profile_bundle(config)
    profile_data = _as_dict(profile)
    cv = _as_dict(master_cv)
    contact = cv.get("contact") or profile_data.get("contact") or {}
    name = html.escape(contact.get("name") or "Data / AI Portfolio")
    summary = html.escape(cv.get("summary") or profile_data.get("summary") or "")
    tagline = html.escape(cfg.tagline or "Building data-driven systems for Paris-based teams.")
    photo = _photo_asset(config)
    skills = _listify(cv.get("skills") or profile_data.get("skills"), 24)
    projects = (cv.get("projects") or [])[:6]
    experience = (cv.get("experience") or [])[:5]
    education = (cv.get("education") or [])[:3]
    github = html.escape(contact.get("github_url") or "")
    linkedin = html.escape(contact.get("linkedin_url") or "")
    email = html.escape(contact.get("email") or "")
    location = html.escape(contact.get("location") or "")
    google_font = FONTS.get(cfg.font, {}).get("google", "")
    font_link = (
        f'\n  <link rel="preconnect" href="https://fonts.googleapis.com" />'
        f'\n  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />'
        f'\n  <link href="https://fonts.googleapis.com/css2?family={google_font}&display=swap" rel="stylesheet" />'
    ) if google_font else ""

    portrait_html = ""
    if photo and cfg.layout == "split":
        portrait_html = f'<div><img class="portrait" data-reveal src="{html.escape(photo)}" alt="{name} portrait" /></div>'

    nav_items = ['<a href="#about">About</a>', '<a href="#projects">Projects</a>', '<a href="#experience">Experience</a>', '<a href="#skills">Skills</a>', '<a href="#contact">Contact</a>']

    def project_card(idx: int, project: dict[str, Any]) -> str:
        name_p = html.escape(project.get("name") or "Project")
        desc = html.escape(project.get("description") or "")
        url = html.escape(project.get("url") or "")
        tech = "".join(f'<span class="chip">{html.escape(str(t))}</span>' for t in (project.get("technologies") or [])[:8])
        bullets = "".join(f"<li>{html.escape(str(b))}</li>" for b in (project.get("bullet_points") or [])[:3])
        link = f'<a class="btn" href="{url}" target="_blank" rel="noreferrer">View project →</a>' if url else ""
        return f'<article class="card" data-reveal="{idx}"><h3>{name_p}</h3><p class="muted">{desc}</p><ul>{bullets}</ul><div class="chips">{tech}</div><div class="actions">{link}</div></article>'

    def job_item(idx: int, job: dict[str, Any]) -> str:
        period = html.escape(" – ".join([str(job.get("start_date") or ""), str(job.get("end_date") or "Present")]).strip(" –"))
        heading = html.escape(f"{job.get('title') or ''} · {job.get('company') or ''}".strip(" ·"))
        location_part = html.escape(job.get("location") or "")
        bullets = "".join(f"<li>{html.escape(str(b))}</li>" for b in (job.get("bullet_points") or [])[:4])
        return f'<div class="job" data-reveal="{idx}"><div><strong class="muted">{period}</strong><br><small class="muted">{location_part}</small></div><div><h3>{heading}</h3><ul>{bullets}</ul></div></div>'

    def education_item(idx: int, edu: dict[str, Any]) -> str:
        years = html.escape(" – ".join([str(edu.get("start_year") or ""), str(edu.get("end_year") or "")]).strip(" –"))
        degree = html.escape(f"{edu.get('degree') or ''} {edu.get('field') or ''}".strip())
        school = html.escape(edu.get("institution") or "")
        return f'<div class="job" data-reveal="{idx}"><div><strong class="muted">{years}</strong></div><div><h3>{degree}</h3><p class="muted">{school}</p></div></div>'

    skills_html = "".join(f'<span class="chip">{html.escape(skill)}</span>' for skill in skills)
    projects_html = "".join(project_card(i, p) for i, p in enumerate(projects))
    experience_html = "".join(job_item(i, j) for i, j in enumerate(experience))
    education_html = "".join(education_item(i, e) for i, e in enumerate(education))

    # Reorderable middle sections, keyed for cfg.section_order placement.
    projects_body = projects_html or '<p class="muted">No projects yet. Add one in profiles/master_cv.json.</p>'
    experience_body = experience_html or '<p class="muted">No experience yet.</p>'
    education_body = education_html or '<p class="muted">No education yet.</p>'
    middle_sections = {
        "skills": f'<section class="section" id="skills"><div class="wrap"><h2 data-reveal>Core stack</h2><div class="chips" data-reveal>{skills_html}</div></div></section>',
        "projects": f'<section class="section" id="projects"><div class="wrap"><h2 data-reveal>Selected projects</h2><div class="grid">{projects_body}</div></div></section>',
        "experience": f'<section class="section" id="experience"><div class="wrap"><h2 data-reveal>Experience</h2><div class="timeline">{experience_body}</div></div></section>',
        "education": f'<section class="section" id="education"><div class="wrap"><h2 data-reveal>Education</h2><div class="timeline">{education_body}</div></div></section>',
    }

    # Optional sections — only render when toggled on.
    sections = cfg.sections or {}
    optional_blocks: list[str] = []
    section_meta = {
        "open_source": ("Open Source", "Notable contributions, maintained repos, and PRs to public projects.", "open-source"),
        "speaking": ("Speaking", "Talks, meetups, conferences, podcasts.", "speaking"),
        "awards": ("Awards & Recognition", "Hackathons, scholarships, fellowships, honors.", "awards"),
        "testimonials": ("Testimonials", "What managers, professors, and collaborators say about working together.", "testimonials"),
        "blog": ("Writing", "Blog posts, deep dives, lessons learned.", "blog"),
    }
    for key in OPTIONAL_SECTIONS:
        if not sections.get(key):
            continue
        title, blurb, anchor = section_meta[key]
        optional_blocks.append(
            f'<section class="section" id="{anchor}"><div class="wrap"><h2 data-reveal>{title}</h2>'
            f'<p class="lead" data-reveal>{blurb}</p>'
            f'{_section_card_html([], 0)}</div></section>'
        )

    hero_inner = f'''
        <div data-reveal>
          <div class="eyebrow">{tagline}</div>
          <h1 class="headline"><span class="accent">{name}</span></h1>
          <p class="lead">{summary}</p>
          <div class="actions">
            {f'<a class="btn primary" href="mailto:{email}">Contact me</a>' if email else ''}
            {f'<a class="btn" href="{github}" target="_blank" rel="noreferrer">GitHub</a>' if github else ''}
            {f'<a class="btn" href="{linkedin}" target="_blank" rel="noreferrer">LinkedIn</a>' if linkedin else ''}
            <a class="btn" href="cv.pdf">Download CV</a>
          </div>
        </div>
        {portrait_html}
    '''

    dark_toggle = '<button class="toggle-theme" data-toggle-theme aria-label="Toggle dark mode">◐ Theme</button>' if cfg.enable_dark_toggle else ""

    meta_title = f"{name} · {html.escape(cfg.site_title_suffix or 'Portfolio')}"
    og_desc = (summary or tagline)[:200]
    site_meta = _site_url_meta(cfg)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{meta_title}</title>
  <meta name="description" content="{html.escape(og_desc)}" />
  <meta property="og:title" content="{meta_title}" />
  <meta property="og:description" content="{html.escape(og_desc)}" />
  <meta property="og:type" content="profile" />
  <meta name="twitter:card" content="summary_large_image" />{site_meta}{font_link}
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <header class="site"><div class="wrap">
    <div class="brand">{name}</div>
    <nav>{''.join(nav_items)}{dark_toggle}</nav>
  </div></header>
  <main>
    <section class="hero" id="about"><div class="wrap hero-grid {cfg.layout}">{hero_inner}</div></section>
    {''.join(middle_sections[key] for key in cfg.section_order)}
    {''.join(optional_blocks)}
    <section class="section" id="contact"><div class="wrap"><h2 data-reveal>Contact</h2>
      <dl class="kv">
        {f'<dt>Email</dt><dd><a href="mailto:{email}">{email}</a></dd>' if email else ''}
        {f'<dt>GitHub</dt><dd><a href="{github}" target="_blank" rel="noreferrer">{github}</a></dd>' if github else ''}
        {f'<dt>LinkedIn</dt><dd><a href="{linkedin}" target="_blank" rel="noreferrer">{linkedin}</a></dd>' if linkedin else ''}
        {f'<dt>Location</dt><dd>{location}</dd>' if location else ''}
      </dl>
    </div></section>
  </main>
  <footer><div class="wrap">
    <span class="muted">© {name} · built locally with Paris Data Career Copilot.</span>
    <span class="muted print-hint">Tip: Press Ctrl/Cmd + P for a clean printable resume.</span>
  </div></footer>
  <script>
  (function(){{
    var stored = null;
    try {{ stored = localStorage.getItem('portfolio-theme'); }} catch (e) {{}}
    if (stored === 'dark' || stored === 'forced-light') document.documentElement.dataset.theme = stored;
    var btn = document.querySelector('[data-toggle-theme]');
    if (btn) btn.addEventListener('click', function () {{
      var current = document.documentElement.dataset.theme || '';
      var next = current === 'dark' ? 'forced-light' : 'dark';
      document.documentElement.dataset.theme = next;
      try {{ localStorage.setItem('portfolio-theme', next); }} catch (e) {{}}
    }});
    var anims = document.querySelectorAll('[data-reveal]');
    if ('IntersectionObserver' in window) {{
      var io = new IntersectionObserver(function (entries) {{
        entries.forEach(function (entry) {{ if (entry.isIntersecting) {{ entry.target.classList.add('in'); io.unobserve(entry.target); }} }});
      }}, {{ rootMargin: '0px 0px -10% 0px', threshold: 0.05 }});
      anims.forEach(function (el) {{ io.observe(el); }});
    }} else {{
      anims.forEach(function (el) {{ el.classList.add('in'); }});
    }}
  }})();
  </script>
</body>
</html>
"""


def _render_robots(cfg: PortfolioConfig) -> str:
    return "User-agent: *\nAllow: /\n" + (f"\nSitemap: {cfg.site_url.rstrip('/')}/sitemap.xml\n" if cfg.site_url else "")


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
