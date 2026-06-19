"""CV Studio — profile asset management and contact-icon pack picker.

Public functions here (``list_assets``, ``read_asset``, ``write_asset``,
``replace_photo``, ``remove_photo``, ``apply_icon_pack``) are re-exported by
:mod:`job_agent.cv_studio`. Shared primitives come from
:mod:`job_agent.cv_studio_core`; this module never imports ``cv_studio`` back.
"""
from __future__ import annotations

import base64
import binascii
import re
import shutil
from pathlib import Path
from typing import Any

from job_agent.config import AppConfig
from job_agent.cv_studio_core import (
    _IMAGE_ASSET_SUFFIXES,
    _TEXT_ASSET_SUFFIXES,
    _active_cv_text,
    _profiles_root,
    _safe_asset_path,
    _write_draft,
)


# -----------------------------------------------------------------------------
# Asset management
# -----------------------------------------------------------------------------


def list_assets(config: AppConfig) -> list[dict[str, Any]]:
    """Return all asset files in the profiles directory."""
    try:
        root = _profiles_root(config)
    except ValueError:
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if path.is_dir():
            continue
        if path.suffix.lower() not in _TEXT_ASSET_SUFFIXES | _IMAGE_ASSET_SUFFIXES:
            continue
        items.append({
            "name": path.name,
            "kind": "text" if path.suffix.lower() in _TEXT_ASSET_SUFFIXES else "image",
            "size": path.stat().st_size,
            "modified": path.stat().st_mtime,
        })
    return items


def read_asset(config: AppConfig, name: str) -> dict[str, Any]:
    """Read a text asset's contents (returns base64 for images)."""
    path = _safe_asset_path(config, name)
    if not path.exists():
        return {"ok": False, "reason": "not_found"}
    kind = "text" if path.suffix.lower() in _TEXT_ASSET_SUFFIXES else "image"
    if kind == "text":
        return {"ok": True, "kind": "text", "name": path.name, "text": path.read_text(encoding="utf-8", errors="replace")}
    return {"ok": True, "kind": "image", "name": path.name, "url": f"/file?path={path}"}


def write_asset(config: AppConfig, name: str, text: str) -> dict[str, Any]:
    """Overwrite a text asset under profiles/. Keeps a .bak of the previous content."""
    path = _safe_asset_path(config, name)
    if path.suffix.lower() not in _TEXT_ASSET_SUFFIXES:
        return {"ok": False, "reason": "binary_asset"}
    if path.exists():
        try:
            shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
        except Exception:
            pass
    path.write_text(text or "", encoding="utf-8")
    return {"ok": True, "name": path.name, "size": path.stat().st_size}


def replace_photo(config: AppConfig, name: str, base64_data: str) -> dict[str, Any]:
    """Replace (or create) a CV photo from a base64-encoded data URL."""
    try:
        root = _profiles_root(config)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    # Strip "data:image/jpeg;base64,..." prefix if present.
    payload = base64_data or ""
    if "," in payload[:80]:
        payload = payload.split(",", 1)[1]
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return {"ok": False, "reason": "invalid_base64"}
    safe_name = Path(name or "me.jpg").name
    if Path(safe_name).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        safe_name = "me.jpg"
    target = root / safe_name
    if target.exists():
        try:
            shutil.copyfile(target, target.with_suffix(target.suffix + ".bak"))
        except Exception:
            pass
    target.write_bytes(raw)
    return {"ok": True, "name": safe_name, "bytes": len(raw)}


def remove_photo(config: AppConfig, name: str = "me.jpg") -> dict[str, Any]:
    """Comment out the ``\\photo{...}`` line in main.tex and delete the photo file."""
    try:
        root = _profiles_root(config)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    main = root / "main.tex"
    if main.exists():
        text = main.read_text(encoding="utf-8")
        new_text = re.sub(r"^(\\photo\[[^\]]*\])?\{[^}]+\}", lambda m: "% " + m.group(0), text, count=1, flags=re.MULTILINE)
        if new_text != text:
            main.with_suffix(".tex.bak").write_text(text, encoding="utf-8")
            main.write_text(new_text, encoding="utf-8")
    safe_name = Path(name or "me.jpg").name
    photo = root / safe_name
    if photo.exists():
        try:
            shutil.copyfile(photo, photo.with_suffix(photo.suffix + ".bak"))
            photo.unlink()
        except Exception:
            pass
    return {"ok": True}


# -----------------------------------------------------------------------------
# Icon pack picker
# -----------------------------------------------------------------------------


ICON_PACKS = {
    "moderncv": {
        "label": "moderncv default (text)",
        "phone": r"\phone[mobile]{",
        "email": r"\email{",
        "linkedin": r"\social[linkedin]{",
        "github": r"\social[github]{",
        "snippet": "% moderncv default contact lines (text labels).",
    },
    "fontawesome": {
        "label": "FontAwesome 5 (icons)",
        "snippet": (
            "% Replaces text contact labels with FontAwesome icons.\n"
            "\\usepackage{fontawesome5}\n"
        ),
        # Drop-in renames keep the moderncv layout intact.
        # Use direct command names instead of \faIcon{...}; the repo ships a
        # tiny local fontawesome5.sty fallback for MiKTeX installs that do not
        # have the full package yet.
        "phone": r"\renewcommand*\phonesymbol{\faMobile*~}",
        "email": r"\renewcommand*\emailsymbol{\faEnvelope~}",
        "linkedin": r"\renewcommand*\linkedinsocialsymbol{\faLinkedin~}",
        "github": r"\renewcommand*\githubsocialsymbol{\faGithub~}",
    },
    "academicons": {
        "label": "Academicons (research icons)",
        "snippet": (
            "% Academicons preview pack: kept as comments unless academicons.sty is present.\n"
        ),
        "phone": r"% phone icon kept as moderncv default",
        "email": r"% email icon kept as moderncv default",
        "linkedin": r"% linkedin icon kept as moderncv default",
        "github": r"% github icon kept as moderncv default",
    },
}


_ICON_BLOCK_RE = re.compile(
    r"% --- BEGIN CV-STUDIO ICON PACK ---.*?% --- END CV-STUDIO ICON PACK ---\n?",
    flags=re.DOTALL,
)


def _icon_pack_block(pack: str, pack_data: dict[str, Any]) -> str:
    block_lines = ["% --- BEGIN CV-STUDIO ICON PACK ---", str(pack_data["snippet"]).rstrip()]
    if pack == "fontawesome":
        block_lines.extend([pack_data["phone"], pack_data["email"], pack_data["linkedin"], pack_data["github"]])
    elif pack == "academicons":
        # Academicons doesn't redefine moderncv hooks; the chosen pack remains
        # visible in source and can be extended when academicons.sty is present.
        pass
    block_lines.append("% --- END CV-STUDIO ICON PACK ---")
    return "\n".join(block_lines) + "\n"


def _apply_icon_pack_to_text(text: str, pack: str, pack_data: dict[str, Any]) -> str:
    text = _ICON_BLOCK_RE.sub("", text or "")
    block = _icon_pack_block(pack, pack_data)
    if r"\begin{document}" in text:
        return text.replace(r"\begin{document}", block + r"\begin{document}", 1)
    return text.rstrip() + "\n\n" + block


def apply_icon_pack(config: AppConfig, pack: str) -> dict[str, Any]:
    """Inject the chosen icon pack's directives into main.tex and the draft."""
    try:
        root = _profiles_root(config)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    main = root / "main.tex"
    if not main.exists():
        return {"ok": False, "reason": "no_main_tex"}
    pack_data = ICON_PACKS.get(pack)
    if not pack_data:
        return {"ok": False, "reason": "unknown_pack"}
    original_main = main.read_text(encoding="utf-8")
    main_text = _apply_icon_pack_to_text(original_main, pack, pack_data)
    main.with_suffix(".tex.bak").write_text(original_main, encoding="utf-8")
    main.write_text(main_text, encoding="utf-8")

    # Compile Preview reads the Studio draft when it exists. Keep the draft in
    # sync so choosing an icon pack has an immediate visible effect.
    active_text, active_path, origin = _active_cv_text(config)
    preview_text = main_text
    if active_path and origin == "draft":
        preview_text = _apply_icon_pack_to_text(active_text, pack, pack_data)
        active_path.with_suffix(".tex.bak").write_text(active_text, encoding="utf-8")
        active_path.write_text(preview_text, encoding="utf-8")
    else:
        _write_draft(config, main_text)

    return {"ok": True, "pack": pack, "label": pack_data["label"], "text": preview_text}
