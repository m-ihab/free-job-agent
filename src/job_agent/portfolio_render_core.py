"""Shared portfolio primitives: themes, fonts, the ``PortfolioConfig`` dataclass,
and small filesystem/data helpers.

This is the base of the portfolio rendering layer. The CSS / HTML / SEO renderers
import from here; nothing here imports them, so there is no import cycle. The
public facade lives in :mod:`job_agent.portfolio_render`, which re-exports these.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from job_agent.config import AppConfig


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
    # Local-first defaults: don't invite crawlers and don't phone Google Fonts
    # home unless the user is deliberately publishing a public portfolio.
    public_mode: bool = False
    use_google_fonts: bool = False

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
