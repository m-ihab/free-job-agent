"""Local portfolio-site builder.

The portfolio builder turns the local profile bundle into a static, editable
website under ``.job_agent/portfolio``. Nothing is published automatically; the
export/publish flows create local artifacts and instructions the user controls.
"""
from __future__ import annotations

import html
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from job_agent.config import AppConfig
from job_agent.validators import load_profile_bundle

try:
    from job_agent.ai_agent import is_available as _ai_is_available
    from job_agent.ai_agent import _call_ollama_json as _ai_call_json  # type: ignore[attr-defined]
    from job_agent.polish import PolishOptions
except Exception:  # pragma: no cover - AI is optional
    _ai_is_available = None  # type: ignore[assignment]
    _ai_call_json = None  # type: ignore[assignment]
    PolishOptions = None  # type: ignore[assignment]


THEMES: dict[str, dict[str, str]] = {
    "signal": {
        "label": "Signal",
        "bg": "#f8fafc",
        "ink": "#0f172a",
        "muted": "#475569",
        "surface": "#ffffff",
        "accent": "#2563eb",
        "accent2": "#14b8a6",
    },
    "midnight": {
        "label": "Midnight Lab",
        "bg": "#07111f",
        "ink": "#e5edf8",
        "muted": "#9fb2ca",
        "surface": "#0d1b2d",
        "accent": "#38bdf8",
        "accent2": "#a78bfa",
    },
    "editorial": {
        "label": "Editorial",
        "bg": "#fbfaf8",
        "ink": "#171717",
        "muted": "#5f5b55",
        "surface": "#ffffff",
        "accent": "#b45309",
        "accent2": "#0f766e",
    },
    "terminal": {
        "label": "Terminal",
        "bg": "#07130c",
        "ink": "#e8ffe8",
        "muted": "#9ac99a",
        "surface": "#0d1d13",
        "accent": "#22c55e",
        "accent2": "#facc15",
    },
}

FONTS = {
    "inter": {"label": "Inter / system", "stack": "Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"},
    "plex": {"label": "IBM Plex Sans", "stack": "'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif"},
    "space": {"label": "Space Grotesk", "stack": "'Space Grotesk', ui-sans-serif, system-ui, sans-serif"},
    "mono": {"label": "Technical Mono", "stack": "'JetBrains Mono', 'Cascadia Code', ui-monospace, SFMono-Regular, monospace"},
}


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


def portfolio_state(config: AppConfig) -> dict[str, Any]:
    out = _portfolio_dir(config)
    return {
        "ok": True,
        "path": str(out),
        "html_path": str(out / "index.html"),
        "css_path": str(out / "style.css"),
        "exists": (out / "index.html").exists(),
        "themes": [{"key": key, "label": value["label"]} for key, value in THEMES.items()],
        "fonts": [{"key": key, "label": value["label"]} for key, value in FONTS.items()],
    }


def _render_css(theme_key: str, font_key: str) -> str:
    theme = THEMES.get(theme_key, THEMES["signal"])
    font = FONTS.get(font_key, FONTS["inter"])
    return f""":root {{
  --bg: {theme['bg']};
  --ink: {theme['ink']};
  --muted: {theme['muted']};
  --surface: {theme['surface']};
  --accent: {theme['accent']};
  --accent-2: {theme['accent2']};
  --font: {font['stack']};
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  font-family: var(--font);
  background: var(--bg);
  color: var(--ink);
  line-height: 1.6;
}}
a {{ color: inherit; }}
.wrap {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; }}
.hero {{ min-height: 82vh; display: grid; place-items: center; padding: 64px 0 42px; }}
.hero-grid {{ display: grid; grid-template-columns: 1.25fr 0.75fr; gap: 42px; align-items: center; }}
.eyebrow {{ color: var(--accent); text-transform: uppercase; font-size: 0.78rem; font-weight: 800; letter-spacing: 0; }}
h1 {{ font-size: clamp(2.4rem, 7vw, 5.8rem); line-height: 0.95; margin: 10px 0 18px; letter-spacing: 0; }}
.lead {{ color: var(--muted); font-size: clamp(1.05rem, 2vw, 1.35rem); max-width: 62ch; }}
.portrait {{ width: min(320px, 72vw); aspect-ratio: 1; object-fit: cover; border-radius: 24px; border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent); box-shadow: 0 30px 80px color-mix(in srgb, var(--accent) 18%, transparent); }}
.actions {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }}
.btn {{ border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); border-radius: 999px; padding: 11px 16px; text-decoration: none; font-weight: 800; }}
.btn.primary {{ background: var(--accent); color: white; }}
.section {{ padding: 58px 0; border-top: 1px solid color-mix(in srgb, var(--muted) 18%, transparent); }}
.section h2 {{ font-size: clamp(1.7rem, 3vw, 2.6rem); margin: 0 0 22px; letter-spacing: 0; }}
.grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }}
.card {{ background: color-mix(in srgb, var(--surface) 92%, transparent); border: 1px solid color-mix(in srgb, var(--muted) 18%, transparent); border-radius: 18px; padding: 22px; box-shadow: 0 18px 50px rgba(0,0,0,0.08); }}
.card h3 {{ margin: 0 0 8px; }}
.muted {{ color: var(--muted); }}
.chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.chip {{ padding: 7px 10px; border-radius: 999px; background: color-mix(in srgb, var(--accent) 13%, transparent); color: var(--ink); font-weight: 700; font-size: 0.85rem; }}
.timeline {{ display: grid; gap: 16px; }}
.job {{ display: grid; grid-template-columns: 180px 1fr; gap: 18px; }}
footer {{ padding: 36px 0 56px; color: var(--muted); }}
@media (max-width: 820px) {{
  .hero-grid, .grid, .job {{ grid-template-columns: 1fr; }}
  .hero {{ min-height: auto; }}
}}
"""


def _render_html(config: AppConfig, theme_key: str, font_key: str) -> str:
    profile, master_cv, _ = load_profile_bundle(config)
    profile_data = _as_dict(profile)
    cv = _as_dict(master_cv)
    contact = cv.get("contact") or profile_data.get("contact") or {}
    name = html.escape(contact.get("name") or "Data / AI Portfolio")
    title = html.escape("Data Science & AI Engineering")
    summary = html.escape(cv.get("summary") or profile_data.get("summary") or "")
    photo = _photo_asset(config)
    skills = _listify(cv.get("skills") or profile_data.get("skills"), 18)
    projects = (cv.get("projects") or [])[:6]
    experience = (cv.get("experience") or [])[:4]
    github = html.escape(contact.get("github_url") or "")
    linkedin = html.escape(contact.get("linkedin_url") or "")
    email = html.escape(contact.get("email") or "")
    photo_html = f'<img class="portrait" src="{html.escape(photo)}" alt="{name} portrait" />' if photo else ""

    def project_card(project: dict[str, Any]) -> str:
        name_p = html.escape(project.get("name") or "Project")
        desc = html.escape(project.get("description") or "")
        url = html.escape(project.get("url") or "")
        tech = "".join(f'<span class="chip">{html.escape(str(t))}</span>' for t in (project.get("technologies") or [])[:8])
        bullets = "".join(f"<li>{html.escape(str(b))}</li>" for b in (project.get("bullet_points") or [])[:3])
        link = f'<a class="btn" href="{url}" target="_blank" rel="noreferrer">View project</a>' if url else ""
        return f'<article class="card"><h3>{name_p}</h3><p class="muted">{desc}</p><ul>{bullets}</ul><div class="chips">{tech}</div><div class="actions">{link}</div></article>'

    def job_item(job: dict[str, Any]) -> str:
        period = html.escape(" - ".join([str(job.get("start_date") or ""), str(job.get("end_date") or "Present")]).strip(" -"))
        heading = html.escape(f"{job.get('title') or ''} · {job.get('company') or ''}".strip(" ·"))
        bullets = "".join(f"<li>{html.escape(str(b))}</li>" for b in (job.get("bullet_points") or [])[:3])
        return f'<div class="card job"><strong class="muted">{period}</strong><div><h3>{heading}</h3><ul>{bullets}</ul></div></div>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{name} · Portfolio</title>
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <main>
    <section class="hero">
      <div class="wrap hero-grid">
        <div>
          <div class="eyebrow">Paris · Data · AI</div>
          <h1>{name}</h1>
          <p class="lead">{summary}</p>
          <div class="actions">
            {f'<a class="btn primary" href="mailto:{email}">Contact</a>' if email else ''}
            {f'<a class="btn" href="{github}" target="_blank" rel="noreferrer">GitHub</a>' if github else ''}
            {f'<a class="btn" href="{linkedin}" target="_blank" rel="noreferrer">LinkedIn</a>' if linkedin else ''}
          </div>
        </div>
        <div>{photo_html}</div>
      </div>
    </section>
    <section class="section"><div class="wrap"><h2>Core stack</h2><div class="chips">{''.join(f'<span class="chip">{html.escape(skill)}</span>' for skill in skills)}</div></div></section>
    <section class="section"><div class="wrap"><h2>Selected projects</h2><div class="grid">{''.join(project_card(p) for p in projects)}</div></div></section>
    <section class="section"><div class="wrap"><h2>Experience</h2><div class="timeline">{''.join(job_item(j) for j in experience)}</div></div></section>
  </main>
  <footer><div class="wrap">Built locally with Paris Data Career Copilot. Exported static site.</div></footer>
</body>
</html>
"""


def generate_portfolio(config: AppConfig, *, theme: str = "signal", font: str = "inter") -> dict[str, Any]:
    out = _portfolio_dir(config)
    html_text = _render_html(config, theme, font)
    css_text = _render_css(theme, font)
    (out / "index.html").write_text(html_text, encoding="utf-8")
    (out / "style.css").write_text(css_text, encoding="utf-8")
    (out / "portfolio.json").write_text(json.dumps({"theme": theme, "font": font}, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(out), "html": html_text, "css": css_text}


def read_portfolio(config: AppConfig) -> dict[str, Any]:
    out = _portfolio_dir(config)
    html_path = out / "index.html"
    css_path = out / "style.css"
    if not html_path.exists() or not css_path.exists():
        generated = generate_portfolio(config)
        return {**portfolio_state(config), **generated}
    return {
        **portfolio_state(config),
        "html": html_path.read_text(encoding="utf-8", errors="replace"),
        "css": css_path.read_text(encoding="utf-8", errors="replace"),
    }


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
            if path.is_file() and path.name != zip_path.name:
                zf.write(path, arcname=path.name)
    return zip_path


def publish_guide(config: AppConfig) -> dict[str, Any]:
    out = _portfolio_dir(config)
    guide = out / "PUBLISHING.md"
    guide.write_text(
        "# Publishing checklist\n\n"
        "1. Review `index.html` and `style.css` locally in the Portfolio Builder.\n"
        "2. Click Export ZIP and inspect the archive.\n"
        "3. For GitHub Pages: create a public repo, upload `index.html`, `style.css`, and image assets, then enable Pages from the main branch.\n"
        "4. For Netlify/Vercel: drag the exported folder or ZIP into their dashboard.\n"
        "5. Never upload `.env.local`, `jobs.db`, or the `profiles/` source files unless you intentionally want them public.\n",
        encoding="utf-8",
    )
    return {"ok": True, "path": str(guide), "message": "Publish guide generated locally."}


def portfolio_suggestions(config: AppConfig) -> dict[str, Any]:
    deterministic = [
        {
            "title": "Lead with one strong proof point",
            "detail": "Move your best AI/deep-learning project into the first project card and make the first sentence model-focused.",
        },
        {
            "title": "Add a recruiter path",
            "detail": "Keep Contact, GitHub, and LinkedIn visible in the first viewport so the portfolio works as an application companion.",
        },
        {
            "title": "Use contrast, not clutter",
            "detail": "Pick one accent color and reserve it for calls to action, project tags, and section anchors.",
        },
    ]
    if _ai_is_available is None or _ai_call_json is None or PolishOptions is None:
        return {"available": False, "suggestions": deterministic}
    opts = PolishOptions.from_env()
    if not _ai_is_available(opts):
        return {"available": False, "suggestions": deterministic}
    profile, master_cv, _ = load_profile_bundle(config)
    prompt = (
        "Return JSON only: {\"suggestions\":[{\"title\":\"...\",\"detail\":\"...\"}]}.\n"
        "Give 4 concise portfolio design/content suggestions for this data/AI candidate. "
        "Do not invent metrics.\n"
        f"Summary: {master_cv.summary or profile.summary}\n"
        f"Skills: {', '.join(master_cv.all_skill_names()[:40])}\n"
        f"Projects: {', '.join(p.name for p in master_cv.projects[:8])}\n"
    )
    raw = _ai_call_json(prompt, opts)
    items = raw.get("suggestions") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return {"available": True, "suggestions": deterministic}
    suggestions = []
    for item in items[:6]:
        if isinstance(item, dict) and item.get("title"):
            suggestions.append({
                "title": str(item.get("title") or "")[:100],
                "detail": str(item.get("detail") or "")[:320],
            })
    return {"available": True, "suggestions": suggestions or deterministic}
