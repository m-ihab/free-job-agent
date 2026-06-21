"""Portfolio HTML renderer: three hero layouts + optional/reorderable sections."""
from __future__ import annotations

import html
from typing import Any

from job_agent.config import AppConfig
from job_agent.portfolio_render_core import (
    FONTS,
    OPTIONAL_SECTIONS,
    PortfolioConfig,
    _as_dict,
    _listify,
    _photo_asset,
)
from job_agent.validators import load_profile_bundle


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
    google_font = FONTS.get(cfg.font, {}).get("google", "") if cfg.use_google_fonts else ""
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
