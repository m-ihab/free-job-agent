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

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from job_agent.config import AppConfig
from job_agent.validators import load_profile_bundle

# Presentation layer (themes, fonts, config dataclass, HTML/CSS renderers) lives
# in ``portfolio_render``. Re-imported here so the public import paths
# (``from job_agent.portfolio_builder import THEMES, PortfolioConfig,
# _section_card_html`` etc.) keep working unchanged.
from job_agent.portfolio_render import (
    FONTS,
    HERO_LAYOUTS,
    OPTIONAL_SECTIONS,
    THEMES,
    PortfolioConfig,
    _portfolio_dir,
    _render_css,
    _render_html,
    _render_robots,
    _render_sitemap,
    _section_card_html,
)

try:
    from job_agent.ai_agent import _call_ollama_json as _ai_call_json  # type: ignore[attr-defined]
    from job_agent.ai_agent import is_available as _ai_is_available
    from job_agent.polish import PolishOptions, _tokens  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    _ai_is_available = None  # type: ignore[assignment]
    _ai_call_json = None  # type: ignore[assignment]
    PolishOptions = None  # type: ignore[assignment,misc]
    _tokens = None  # type: ignore[assignment]


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


_PUBLISH_HOSTS: dict[str, dict[str, Any]] = {
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
        params: dict[str, Any] = {"sort": "updated", "per_page": min(limit, 30)}
        response = requests.get(
            f"https://api.github.com/users/{handle}/repos",
            params=params,
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
    "_section_card_html",
]
