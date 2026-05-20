"""Convert Markdown to a complete HTML document."""
from __future__ import annotations

import html
import re

_CSS = """
body { font-family: Arial, sans-serif; max-width: 860px; margin: 40px auto; padding: 0 20px; color: #222; line-height: 1.45; }
h1 { font-size: 2em; border-bottom: 2px solid #333; padding-bottom: 4px; }
h2 { font-size: 1.5em; border-bottom: 1px solid #aaa; padding-bottom: 2px; margin-top: 1.4em; }
h3 { font-size: 1.1em; margin-bottom: 2px; }
ul { margin: 0 0 1em 1.5em; padding: 0; }
li { margin-bottom: 4px; }
p  { margin: 0 0 0.8em; }
em { font-style: italic; }
strong { font-weight: bold; }
a  { color: #0366d6; }
code { background: #f3f3f3; padding: 2px 4px; border-radius: 3px; }
.warning { background:#fff7cc; border:1px solid #e5c100; padding:12px; border-radius:6px; }
"""


def _inline(text: str) -> str:
    """Apply safe inline markdown conversion."""
    placeholders: list[tuple[str, str]] = []

    def _link_repl(match: re.Match[str]) -> str:
        label = html.escape(match.group(1))
        href = html.escape(match.group(2), quote=True)
        token = f"@@LINK{len(placeholders)}@@"
        placeholders.append((token, f'<a href="{href}">{label}</a>'))
        return token

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link_repl, text)
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    for token, replacement in placeholders:
        text = text.replace(html.escape(token), replacement).replace(token, replacement)
    return text


def _md_to_html_body(md: str) -> str:
    lines = md.splitlines()
    html_lines: list[str] = []
    in_ul = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("<!--"):
            continue
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
        elif re.match(r"^[-*]\s+", line):
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            content = re.sub(r"^[-*]\s+", "", line)
            html_lines.append(f"  <li>{_inline(content)}</li>")
        elif stripped == "":
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
        else:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<p>{_inline(line)}</p>")
    if in_ul:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


def render_html(markdown_content: str, title: str = "Document") -> str:
    body = _md_to_html_body(markdown_content)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>{_CSS}</style>
</head>
<body>
{body}
</body>
</html>"""
