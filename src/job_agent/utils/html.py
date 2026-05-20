"""Small HTML helpers that avoid a hard BeautifulSoup dependency."""
from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self, *, blocked_tags: set[str] | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.blocked_tags = blocked_tags or set()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.blocked_tags:
            self._skip_depth += 1
        elif self._skip_depth == 0 and tag in {"br", "p", "div", "li", "section", "article", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.blocked_tags and self._skip_depth > 0:
            self._skip_depth -= 1
        elif self._skip_depth == 0 and tag in {"p", "div", "li", "section", "article", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self.parts.append(data)


@dataclass
class Link:
    href: str
    text: str


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[Link] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        attrs_map = dict(attrs)
        href = attrs_map.get("href")
        if href:
            self._href = href
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = normalize_whitespace(" ".join(self._parts))
            self.links.append(Link(self._href, text))
            self._href = None
            self._parts = []


def normalize_whitespace(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def strip_html(html: str, *, blocked_tags: set[str] | None = None, separator: str = "\n") -> str:
    parser = _TextExtractor(blocked_tags=blocked_tags)
    parser.feed(html or "")
    text = unescape("".join(parser.parts))
    lines = [normalize_whitespace(line) for line in text.splitlines()]
    cleaned = separator.join(line for line in lines if line)
    return cleaned.strip()


def extract_links(html: str) -> list[Link]:
    parser = _LinkExtractor()
    parser.feed(html or "")
    return parser.links
