"""LaTeX asset handling: copy local assets beside cv.tex and drop references to
missing images so a stray ``\\photo``/``\\includegraphics`` can't abort the build.

Imported by :mod:`job_agent.renderer.latex_compile` and re-exported by
:mod:`job_agent.renderer.latex_render` for the historical import paths.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path


def copy_latex_assets(source_dir: Path | str | None, output_dir: Path | str) -> list[Path]:
    """Copy local LaTeX assets such as photos and style files beside cv.tex."""
    if source_dir is None:
        return []
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    copied: list[Path] = []
    for pattern in ["*.jpg", "*.jpeg", "*.png", "*.sty", "*.cls"]:
        for source in source_dir.glob(pattern):
            destination = output_dir / source.name
            if source.resolve() == destination.resolve():
                continue
            shutil.copyfile(source, destination)
            copied.append(destination)
    return copied


def _safe_existing_file(path: Path) -> bool:
    try:
        return path.exists() and path.is_file()
    except OSError:
        return False


_IMAGE_CMD_RE = re.compile(r"\\(?:photo|includegraphics)(?:\[[^\]]*\])*\{([^}]*)\}")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".pdf")


def _image_present(name: str, asset_dir: Path) -> bool:
    """Is the image referenced by ``name`` available next to the .tex file?"""
    name = name.strip().strip('"').lstrip("./")
    if not name:
        return False
    base = Path(name).name
    if Path(name).suffix.lower() in _IMAGE_EXTS:
        candidates = [asset_dir / name, asset_dir / base]
    else:  # moderncv \photo{me} resolves me.jpg/.png/...
        candidates = [asset_dir / f"{stem}{ext}" for stem in (name, base) for ext in _IMAGE_EXTS]
    return any(_safe_existing_file(c) for c in candidates)


def neutralize_missing_images(tex_text: str, asset_dir: Path | str) -> tuple[str, list[str]]:
    """Drop ``\\photo``/``\\includegraphics`` references whose file is absent.

    A missing image makes pdflatex abort fatally ("reading image file failed").
    A CV without a photo is far better than no CV at all, so we degrade
    gracefully: the command is removed (replaced with empty text, safe even when
    nested inline) and the dropped names are returned for logging. Present images
    are left untouched.
    """
    asset_dir = Path(asset_dir)
    removed: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if _image_present(name, asset_dir):
            return match.group(0)
        removed.append(name)
        return ""

    return _IMAGE_CMD_RE.sub(_replace, tex_text), removed
