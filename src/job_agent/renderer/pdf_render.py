"""Render Markdown content to a PDF using ReportLab."""
from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    styles = {
        "h1": ParagraphStyle(
            "H1", parent=base["Normal"], fontSize=18, fontName="Helvetica-Bold",
            spaceAfter=8, spaceBefore=4,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Normal"], fontSize=14, fontName="Helvetica-Bold",
            spaceAfter=6, spaceBefore=10,
        ),
        "h3": ParagraphStyle(
            "H3", parent=base["Normal"], fontSize=12, fontName="Helvetica-Bold",
            spaceAfter=4, spaceBefore=6,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=10, fontName="Helvetica",
            spaceAfter=4, alignment=TA_LEFT,
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base["Normal"], fontSize=10, fontName="Helvetica",
            leftIndent=20, spaceAfter=3, bulletIndent=8,
        ),
    }
    return styles


def _escape_xml(text: str) -> str:
    """Escape XML special characters for ReportLab."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _md_inline(text: str) -> str:
    """Convert inline markdown to ReportLab XML tags."""
    text = _escape_xml(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1', text)
    return text


def render_pdf(
    markdown_content: str,
    output_path: Path | str,
    title: str = "Document",
) -> Path:
    """Render markdown to a PDF file and return the output path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    styles = _build_styles()
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
        title=title,
    )

    story: list = []
    lines = markdown_content.splitlines()

    for line in lines:
        # Skip HTML comments
        if line.strip().startswith("<!--"):
            continue

        if line.startswith("### "):
            story.append(Paragraph(_md_inline(line[4:]), styles["h3"]))
        elif line.startswith("## "):
            story.append(Paragraph(_md_inline(line[3:]), styles["h2"]))
        elif line.startswith("# "):
            story.append(Paragraph(_md_inline(line[2:]), styles["h1"]))
        elif re.match(r'^[-*]\s+', line):
            content = re.sub(r'^[-*]\s+', '', line)
            story.append(Paragraph(f"• {_md_inline(content)}", styles["bullet"]))
        elif line.strip() == "":
            story.append(Spacer(1, 6))
        else:
            story.append(Paragraph(_md_inline(line), styles["body"]))

    doc.build(story)
    return output_path
