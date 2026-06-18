"""Local portfolio-site builder.

The Portfolio Builder turns the local profile bundle into a static, editable
website under ``.job_agent/portfolio``. Nothing is published automatically; the
export/publish flows create local artifacts and instructions the user controls.

Capabilities:
- 11 curated themes + 12 fonts + custom accent color override.
- 3 hero layouts (split / centered / cinematic).
- Optional sections (testimonials, open source, speaking, awards, blog).
- SEO meta + Open Graph card + sitemap.xml + robots.txt.
- Visitor-side dark-mode toggle (no flicker, persists in localStorage).
- Scroll-reveal CSS animations + smooth anchor scroll.
- AI tagline, AI bio polish, AI section copy — all overlap-validated.
- Live GitHub import: rank repos by topics/language/stars, fold READMEs.
- ZIP export + per-host (GitHub Pages / Netlify / Vercel / Cloudflare / Surge)
  publishing instructions.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from job_agent.config import AppConfig
from job_agent.validators import load_profile_bundle

try:
    from job_agent.ai_agent import _call_ollama_json as _ai_call_json  # type: ignore[attr-defined]
    from job_agent.ai_agent import is_available as _ai_is_available
    from job_agent.polish import PolishOptions, _tokens  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    _ai_is_available = None  # type: ignore[assignment]
    _ai_call_json = None  # type: ignore[assignment]
    PolishOptions = None  # type: ignore[assignment]
    _tokens = None  # type: ignore[assignment]


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


@dataclass
class PortfolioConfig:
    theme: str = "signal"
    font: str = "inter"
    layout: str = "split"
    custom_accent: str = ""
    sections: dict[str, bool] = None  # type: ignore[assignment]
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
        return self


def _portfolio_dir(config: AppConfig) -> Path:
    base = Path(config.data_dir or Path.cwd() / ".job_agent") / "portfolio"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _photo_asset(config: AppConfig) -> str:
    profiles = Path(config.profiles_dir or "")
    for name in ("me.jpg", "me.jpeg", "me.png"):
        source = profiles / name
        if source.exists():
            target = _portfolio_dir(config) / name
            try:
                shutil.copyfile(source, target)
                return name
            except Exception:
                return ""
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


def _load_config_file(config: AppConfig) -> PortfolioConfig:
    path = _portfolio_dir(config) / "portfolio.json"
    if not path.exists():
        return PortfolioConfig().normalized()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return PortfolioConfig().normalized()
    cfg = PortfolioConfig(
        theme=str(raw.get("theme") or "signal"),
        font=str(raw.get("font") or "inter"),
        layout=str(raw.get("layout") or "split"),
        custom_accent=str(raw.get("custom_accent") or ""),
        sections={key: bool((raw.get("sections") or {}).get(key)) for key in OPTIONAL_SECTIONS},
        tagline=str(raw.get("tagline") or ""),
        site_url=str(raw.get("site_url") or ""),
        site_title_suffix=str(raw.get("site_title_suffix") or "Portfolio"),
        enable_dark_toggle=bool(raw.get("enable_dark_toggle", True)),
        enable_animations=bool(raw.get("enable_animations", True)),
    )
    return cfg.normalized()


def _save_config_file(config: AppConfig, portfolio_cfg: PortfolioConfig) -> None:
    path = _portfolio_dir(config) / "portfolio.json"
    payload = {
        "theme": portfolio_cfg.theme,
        "font": portfolio_cfg.font,
        "layout": portfolio_cfg.layout,
        "custom_accent": portfolio_cfg.custom_accent,
        "sections": portfolio_cfg.sections or {},
        "tagline": portfolio_cfg.tagline,
        "site_url": portfolio_cfg.site_url,
        "site_title_suffix": portfolio_cfg.site_title_suffix,
        "enable_dark_toggle": portfolio_cfg.enable_dark_toggle,
        "enable_animations": portfolio_cfg.enable_animations,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def portfolio_state(config: AppConfig) -> dict[str, Any]:
    out = _portfolio_dir(config)
    cfg = _load_config_file(config)
    return {
        "ok": True,
        "path": str(out),
        "html_path": str(out / "index.html"),
        "css_path": str(out / "style.css"),
        "exists": (out / "index.html").exists(),
        "themes": [{"key": key, "label": value["label"], "preset": value.get("preset", "light")} for key, value in THEMES.items()],
        "fonts": [{"key": key, "label": value["label"], "google": value.get("google", "")} for key, value in FONTS.items()],
        "layouts": [{"key": key, "label": label} for key, label in HERO_LAYOUTS.items()],
        "optional_sections": list(OPTIONAL_SECTIONS),
        "config": {
            "theme": cfg.theme,
            "font": cfg.font,
            "layout": cfg.layout,
            "custom_accent": cfg.custom_accent,
            "sections": cfg.sections or {},
            "tagline": cfg.tagline,
            "site_url": cfg.site_url,
            "site_title_suffix": cfg.site_title_suffix,
            "enable_dark_toggle": cfg.enable_dark_toggle,
            "enable_animations": cfg.enable_animations,
        },
    }


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
    dark_block = """
@media (prefers-color-scheme: dark) {
  html:not([data-theme="forced-light"]) {
    --bg: #07111f;
    --ink: #e5edf8;
    --muted: #9fb2ca;
    --surface: #0d1b2d;
  }
}
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
    <section class="section" id="skills"><div class="wrap"><h2 data-reveal>Core stack</h2><div class="chips" data-reveal>{skills_html}</div></div></section>
    <section class="section" id="projects"><div class="wrap"><h2 data-reveal>Selected projects</h2><div class="grid">{projects_html or '<p class="muted">No projects yet. Add one in profiles/master_cv.json.</p>'}</div></div></section>
    <section class="section" id="experience"><div class="wrap"><h2 data-reveal>Experience</h2><div class="timeline">{experience_html or '<p class="muted">No experience yet.</p>'}</div></div></section>
    <section class="section" id="education"><div class="wrap"><h2 data-reveal>Education</h2><div class="timeline">{education_html or '<p class="muted">No education yet.</p>'}</div></div></section>
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


def generate_portfolio(config: AppConfig, **overrides: Any) -> dict[str, Any]:
    cfg = _load_config_file(config)
    for key, value in overrides.items():
        if value is None:
            continue
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    cfg = cfg.normalized()
    out = _portfolio_dir(config)
    html_text = _render_html(config, cfg)
    css_text = _render_css(cfg)
    (out / "index.html").write_text(html_text, encoding="utf-8")
    (out / "style.css").write_text(css_text, encoding="utf-8")
    (out / "robots.txt").write_text(_render_robots(cfg), encoding="utf-8")
    sitemap = _render_sitemap(cfg)
    if sitemap:
        (out / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    _save_config_file(config, cfg)
    # Copy cv.pdf if a tailored or master version exists, so the "Download CV"
    # button on the published portfolio works out of the box.
    for cv_candidate in (
        Path(config.profiles_dir or "") / "CV.pdf",
        Path(config.data_dir or "") / "outputs" / "latest_cv.pdf",
    ):
        try:
            if cv_candidate.exists():
                shutil.copyfile(cv_candidate, out / "cv.pdf")
                break
        except Exception:
            continue
    return {"ok": True, "path": str(out), "html": html_text, "css": css_text, "config": cfg.__dict__}


def read_portfolio(config: AppConfig) -> dict[str, Any]:
    out = _portfolio_dir(config)
    html_path = out / "index.html"
    css_path = out / "style.css"
    state = portfolio_state(config)
    if not html_path.exists() or not css_path.exists():
        generated = generate_portfolio(config)
        state.update({"html": generated["html"], "css": generated["css"]})
        state["exists"] = True
        return state
    state.update({
        "html": html_path.read_text(encoding="utf-8", errors="replace"),
        "css": css_path.read_text(encoding="utf-8", errors="replace"),
    })
    return state


def save_portfolio(config: AppConfig, html_text: str, css_text: str) -> dict[str, Any]:
    out = _portfolio_dir(config)
    html_path = out / "index.html"
    css_path = out / "style.css"
    if html_path.exists():
        shutil.copyfile(html_path, html_path.with_suffix(".html.bak"))
    if css_path.exists():
        shutil.copyfile(css_path, css_path.with_suffix(".css.bak"))
    html_path.write_text(html_text or "", encoding="utf-8")
    css_path.write_text(css_text or "", encoding="utf-8")
    return {"ok": True, "path": str(out)}


def export_portfolio_zip(config: AppConfig) -> Path:
    out = _portfolio_dir(config)
    if not (out / "index.html").exists():
        generate_portfolio(config)
    zip_path = out / "portfolio_export.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in out.iterdir():
            if path.is_file() and path.name not in {zip_path.name}:
                zf.write(path, arcname=path.name)
    return zip_path


# ---------------------------------------------------------------------------
# Publish guide — per-host instructions.
# ---------------------------------------------------------------------------


_PUBLISH_HOSTS = {
    "github_pages": {
        "label": "GitHub Pages",
        "free": True,
        "steps": [
            "Create a new public repo (e.g. `your-username.github.io` for a root domain, or any name for a subpath).",
            "Upload index.html, style.css, robots.txt, sitemap.xml, cv.pdf, and the photo (me.jpg).",
            "Open Settings → Pages → Source = `main` branch, root.",
            "Wait ~30s and your site is live at https://your-username.github.io/repo-name/.",
        ],
    },
    "netlify": {
        "label": "Netlify Drop",
        "free": True,
        "steps": [
            "Visit https://app.netlify.com/drop.",
            "Drag the portfolio folder (not the ZIP) into the drop zone.",
            "Netlify gives you a random subdomain immediately; rename via Site settings → Domain.",
        ],
    },
    "vercel": {
        "label": "Vercel",
        "free": True,
        "steps": [
            "Install Vercel CLI (`npm i -g vercel`) or use https://vercel.com/new.",
            "Run `vercel` inside the portfolio folder; press Enter on each prompt.",
            "Vercel deploys with a free *.vercel.app domain and supports custom domains.",
        ],
    },
    "cloudflare_pages": {
        "label": "Cloudflare Pages",
        "free": True,
        "steps": [
            "Push the portfolio to a public GitHub repo.",
            "Open https://dash.cloudflare.com → Pages → Create a project → Connect to Git.",
            "Build command: empty. Output folder: `/` (the repo root).",
            "Click Save and Deploy.",
        ],
    },
    "surge": {
        "label": "Surge.sh (CLI)",
        "free": True,
        "steps": [
            "`npm install -g surge` once.",
            "`cd .job_agent/portfolio && surge .`",
            "Pick a free *.surge.sh subdomain; the site is live in ~5s.",
        ],
    },
}


def publish_guide(config: AppConfig) -> dict[str, Any]:
    out = _portfolio_dir(config)
    guide = out / "PUBLISHING.md"
    lines = ["# Publishing checklist\n"]
    lines.append("Generate the site, review the preview, then pick one of these free hosts:\n")
    for key, host in _PUBLISH_HOSTS.items():
        lines.append(f"## {host['label']}")
        for step in host["steps"]:
            lines.append(f"- {step}")
        lines.append("")
    lines.append("## Safety checklist\n")
    lines.append("- Never commit `.env.local`, `jobs.db`, or anything inside `profiles/`. Only the rendered portfolio folder.")
    lines.append("- Confirm the photo, email, and links you publish are intentionally public.")
    lines.append("- If you set `site_url` in the portfolio config, robots.txt + sitemap.xml will point to it.")
    guide.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(guide), "hosts": _PUBLISH_HOSTS, "message": "Publish guide regenerated."}


# ---------------------------------------------------------------------------
# AI suggestions: deterministic + Ollama-powered variants.
# ---------------------------------------------------------------------------


_DETERMINISTIC_SUGGESTIONS = [
    {"title": "Lead with one strong proof point", "detail": "Move your best AI/deep-learning project into the first project card and make the first sentence model-focused."},
    {"title": "Add a recruiter path", "detail": "Keep Contact, GitHub, and LinkedIn visible in the first viewport so the portfolio works as an application companion."},
    {"title": "One accent, used sparingly", "detail": "Pick a single accent color and reserve it for calls to action, project tags, and section anchors."},
    {"title": "Add a printable resume", "detail": "Press Ctrl+P on the portfolio — the print stylesheet hides the nav and CTA buttons for a clean PDF."},
    {"title": "Cross-link your projects", "detail": "Each project card already shows tech chips; add a screenshot or GIF to the README so the GitHub link sells the project at a glance."},
]


def portfolio_suggestions(config: AppConfig) -> dict[str, Any]:
    if _ai_is_available is None or _ai_call_json is None or PolishOptions is None:
        return {"available": False, "suggestions": _DETERMINISTIC_SUGGESTIONS}
    opts = PolishOptions.from_env()
    if not _ai_is_available(opts):
        return {"available": False, "suggestions": _DETERMINISTIC_SUGGESTIONS}
    profile, master_cv, _ = load_profile_bundle(config)
    prompt = (
        "Return JSON only: {\"suggestions\":[{\"title\":\"...\",\"detail\":\"...\"}]}.\n"
        "Suggest 5 concise portfolio design/content moves for this data/AI candidate. "
        "Do NOT invent metrics. Focus on layout, hierarchy, and storytelling, not generic platitudes.\n"
        f"Summary: {master_cv.summary or profile.summary}\n"
        f"Skills: {', '.join(master_cv.all_skill_names()[:40])}\n"
        f"Projects: {', '.join(p.name for p in master_cv.projects[:8])}\n"
    )
    raw = _ai_call_json(prompt, opts)
    items = raw.get("suggestions") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return {"available": True, "suggestions": _DETERMINISTIC_SUGGESTIONS}
    cleaned = []
    for item in items[:6]:
        if isinstance(item, dict) and item.get("title"):
            cleaned.append({
                "title": str(item.get("title") or "")[:100],
                "detail": str(item.get("detail") or "")[:320],
            })
    return {"available": True, "suggestions": cleaned or _DETERMINISTIC_SUGGESTIONS}


def generate_tagline(config: AppConfig) -> dict[str, Any]:
    """AI-pick a strong portfolio tagline. Falls back to a deterministic phrase."""
    profile, master_cv, _ = load_profile_bundle(config)
    skills = master_cv.all_skill_names()[:8]
    fallback = "Building data-driven systems for Paris-based teams."
    if _ai_is_available is None or _ai_call_json is None or PolishOptions is None:
        return {"available": False, "tagline": fallback}
    opts = PolishOptions.from_env()
    if not _ai_is_available(opts):
        return {"available": False, "tagline": fallback}
    prompt = (
        "Return JSON only: {\"tagline\":\"...\"}.\n"
        "Write one portfolio tagline under 12 words for the candidate. No buzzwords ('synergy', 'innovative'). "
        "No invented metrics. Match the candidate's actual focus.\n"
        f"Summary: {master_cv.summary or profile.summary}\n"
        f"Skills: {', '.join(skills)}\n"
    )
    raw = _ai_call_json(prompt, opts)
    tagline = ""
    if isinstance(raw, dict):
        tagline = str(raw.get("tagline") or "").strip().strip('"').strip("'")
    if not tagline or len(tagline) > 120:
        tagline = fallback
    if _tokens is not None:
        allowed = _tokens((master_cv.summary or "") + " " + " ".join(skills))
        candidate = _tokens(tagline)
        if candidate and allowed and len(candidate & allowed) / max(1, len(candidate)) < 0.25:
            tagline = fallback
    return {"available": True, "tagline": tagline}


# ---------------------------------------------------------------------------
# Deep GitHub import — used by the dashboard's "Import from GitHub" button.
# ---------------------------------------------------------------------------


def fetch_github_repos(handle: str, *, limit: int = 12) -> list[dict[str, Any]]:
    handle = (handle or "").strip().rstrip("/")
    if "/" in handle:
        handle = handle.rsplit("/", 1)[-1]
    if not handle or requests is None:
        return []
    try:
        response = requests.get(
            f"https://api.github.com/users/{handle}/repos",
            params={"sort": "updated", "per_page": min(limit, 30)},
            headers={"Accept": "application/vnd.github+json", "User-Agent": "job-agent"},
            timeout=15,
        )
        response.raise_for_status()
        repos = response.json()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for repo in repos:
        if not isinstance(repo, dict) or repo.get("fork"):
            continue
        out.append({
            "name": repo.get("name") or "",
            "description": (repo.get("description") or "").strip(),
            "url": repo.get("html_url") or "",
            "language": repo.get("language") or "",
            "topics": repo.get("topics") or [],
            "stars": int(repo.get("stargazers_count") or 0),
            "updated_at": repo.get("updated_at") or "",
        })
        if len(out) >= limit:
            break
    return out


def import_repos_to_portfolio(config: AppConfig, repo_names: list[str], *, handle: str = "") -> dict[str, Any]:
    """Promote the chosen GitHub repos to the top of ``master_cv.json::projects``."""
    profiles = Path(config.profiles_dir or "")
    master_path = profiles / "master_cv.json"
    if not master_path.exists():
        return {"ok": False, "reason": "no_master_cv"}
    try:
        master = json.loads(master_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "reason": f"bad_master_cv: {exc}"}
    repos = fetch_github_repos(handle) if handle else []
    name_to_repo = {r["name"].casefold(): r for r in repos}
    existing = master.get("projects", []) or []
    existing_keys = {(p.get("name") or "").casefold() for p in existing if isinstance(p, dict)}
    added: list[str] = []
    new_projects: list[dict[str, Any]] = []
    for name in repo_names:
        key = (name or "").strip().casefold()
        if not key:
            continue
        repo = name_to_repo.get(key)
        if not repo or key in existing_keys:
            continue
        tech_pool = [t for t in [repo.get("language")] + list(repo.get("topics") or []) if t]
        new_projects.append({
            "name": _humanize(repo["name"]),
            "description": repo.get("description") or "Repository imported from GitHub.",
            "url": repo.get("url"),
            "technologies": tech_pool,
            "bullet_points": [],
        })
        added.append(repo["name"])
    if new_projects:
        master["projects"] = new_projects + existing
        master_path.write_text(json.dumps(master, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "added": added}


def _humanize(value: str) -> str:
    cleaned = re.sub(r"[-_.]+", " ", value).strip()
    if not cleaned:
        return value
    parts: list[str] = []
    for token in cleaned.split():
        parts.append(token if (token.isupper() and len(token) <= 4) else token.capitalize())
    return " ".join(parts)


__all__ = [
    "PortfolioConfig",
    "THEMES",
    "FONTS",
    "HERO_LAYOUTS",
    "OPTIONAL_SECTIONS",
    "portfolio_state",
    "read_portfolio",
    "generate_portfolio",
    "save_portfolio",
    "export_portfolio_zip",
    "publish_guide",
    "portfolio_suggestions",
    "generate_tagline",
    "fetch_github_repos",
    "import_repos_to_portfolio",
]
