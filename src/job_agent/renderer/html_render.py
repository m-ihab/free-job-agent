"""Convert Markdown to a complete HTML document."""
from __future__ import annotations

import re


_CSS = """
body { font-family: Arial, sans-serif; max-width: 860px; margin: 40px auto; padding: 0 20px; color: #222; }
h1 { font-size: 2em; border-bottom: 2px solid #333; padding-bottom: 4px; }
h2 { font-size: 1.5em; border-bottom: 1px solid #aaa; padding-bottom: 2px; margin-top: 1.4em; }
h3 { font-size: 1.1em; margin-bottom: 2px; }
ul { margin: 0 0 1em 1.5em; padding: 0; }
li { margin-bottom: 4px; }
p  { margin: 0 0 0.8em; }
em { font-style: italic; }
strong { font-weight: bold; }
a  { color: #0366d6; }
"""


def _md_to_html_body(md: str) -> str:
    """Minimal regex-based Markdown → HTML body conversion."""
    lines = md.splitlines()
    html_lines: list[str] = []
    in_ul = False

    for line in lines:
        # Skip HTML comments
        if line.strip().startswith("<!--"):
            continue

        # Headings
        if line.startswith("### "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h1>{_inline(line[2:])}</h1>")

        # Bullet lists
        elif re.match(r'^[-*]\s+', line):
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            content = re.sub(r'^[-*]\s+', '', line)
            html_lines.append(f"  <li>{_inline(content)}</li>")

        # Empty line
        elif line.strip() == "":
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append("<br>")

        # Regular paragraph line
        else:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<p>{_inline(line)}</p>")

    if in_ul:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


def _inline(text: str) -> str:
    """Apply inline markdown (bold, italic, links)."""
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Italic (avoid matching **)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)
    # Inline links
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    return text


def render_html(markdown_content: str, title: str = "Document") -> str:
    """Convert markdown to a complete HTML document."""
    body = _md_to_html_body(markdown_content)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>{_CSS}</style>
</head>
<body>
{body}
</body>
</html>"""
