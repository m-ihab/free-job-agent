"""MarkItDown-powered document intake.

Converts PDFs, Word docs, and other rich formats to clean Markdown
before feeding into the normalizer. Falls back gracefully when
markitdown is not installed.

Install the extra: pip install "markitdown[all]"
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_MARKITDOWN_AVAILABLE: Optional[bool] = None


def _check_markitdown() -> bool:
    global _MARKITDOWN_AVAILABLE
    if _MARKITDOWN_AVAILABLE is None:
        try:
            import markitdown  # noqa: F401
            _MARKITDOWN_AVAILABLE = True
        except ImportError:
            _MARKITDOWN_AVAILABLE = False
            logger.debug("markitdown not installed; using basic text extraction. "
                         "Run: pip install 'markitdown[all]'")
    return _MARKITDOWN_AVAILABLE


def extract_text_from_file(path: Path) -> Optional[str]:
    """Extract clean text from a document file using markitdown.

    Returns the extracted Markdown string, or None if extraction fails.
    Supported: PDF, DOCX, PPTX, XLSX, images, audio, HTML.
    """
    if not path.exists():
        logger.warning("File not found: %s", path)
        return None

    if not _check_markitdown():
        return _basic_text_extract(path)

    try:
        from markitdown import MarkItDown
        md = MarkItDown(enable_plugins=False)
        result = md.convert(str(path))
        text = result.text_content.strip()
        if not text:
            logger.warning("markitdown returned empty content for %s", path)
            return _basic_text_extract(path)
        logger.info("markitdown extracted %d chars from %s", len(text), path.name)
        return text
    except Exception as exc:
        logger.warning("markitdown failed for %s: %s -- falling back", path.name, exc)
        return _basic_text_extract(path)


def extract_text_from_url(url: str) -> Optional[str]:
    """Fetch a URL and convert to clean Markdown using markitdown."""
    if not _check_markitdown():
        logger.debug("markitdown not available for URL extraction")
        return None
    try:
        from markitdown import MarkItDown
        md = MarkItDown(enable_plugins=False)
        result = md.convert(url)
        text = result.text_content.strip()
        return text or None
    except Exception as exc:
        logger.debug("markitdown URL extraction failed for %s: %s", url, exc)
        return None


def _basic_text_extract(path: Path) -> Optional[str]:
    """Minimal fallback: read plain text files; skip binary formats."""
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md", ".rst", ".text"):
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip() or None
        except Exception:
            return None
    if suffix == ".html":
        try:
            from job_agent.utils.html import strip_html
            return strip_html(path.read_text(encoding="utf-8", errors="replace")) or None
        except Exception:
            return None
    # Binary formats (PDF, DOCX etc.) without markitdown: cannot extract.
    logger.warning(
        "Cannot extract text from %s without markitdown. "
        "Install it with: pip install 'markitdown[all]'",
        path.name,
    )
    return None


def is_available() -> bool:
    """Return True if markitdown is installed and ready."""
    return _check_markitdown()
