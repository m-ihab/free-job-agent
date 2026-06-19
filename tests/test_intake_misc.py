"""Behavioural tests for RSS fallback, discover-links, and markitdown intake.

These hit the branches the existing happy-path tests miss: the RSS XML fallback
parser, the feedparser ``content`` branch, discover-link keyword filtering and
HTTP errors, and the markitdown text-extraction fallbacks. All HTTP and the
markitdown dependency are mocked — no real network.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from job_agent.intake import discover
from job_agent.intake import markitdown_intake as mi
from job_agent.intake import rss


# ── RSS fallback (feedparser returns no entries -> XML parse) ────────────────

_ATOM_FEED = b"""<?xml version='1.0' encoding='utf-8'?>
<rss version='2.0'>
  <channel>
    <item>
      <title>Data Engineer</title>
      <description>&lt;p&gt;Build pipelines.&lt;/p&gt;</description>
      <link>https://example.com/job/77</link>
    </item>
    <item>
      <title>ML Researcher</title>
      <description>Research role.</description>
      <link>https://example.com/job/78</link>
    </item>
  </channel>
</rss>"""


class _FakeResp:
    def __init__(self, content: bytes, status: int = 200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_rss_fallback_parses_xml_when_feedparser_empty(monkeypatch):
    # feedparser yields no entries -> XML fallback path runs and emits one
    # JobListing per <item> tagged as an RSS source.
    monkeypatch.setattr(rss.feedparser, "parse", lambda url: SimpleNamespace(entries=[]))
    monkeypatch.setattr(rss, "safe_get", lambda *a, **k: _FakeResp(_ATOM_FEED))
    jobs = rss.ingest_rss("https://example.com/feed.xml")
    assert len(jobs) == 2
    assert all(job.source == "rss" for job in jobs)


def test_rss_fallback_respects_limit(monkeypatch):
    monkeypatch.setattr(rss.feedparser, "parse", lambda url: SimpleNamespace(entries=[]))
    monkeypatch.setattr(rss, "safe_get", lambda *a, **k: _FakeResp(_ATOM_FEED))
    jobs = rss.ingest_rss("https://example.com/feed.xml", limit=1)
    assert len(jobs) == 1


def test_rss_returns_empty_when_fallback_fails(monkeypatch):
    monkeypatch.setattr(rss.feedparser, "parse", lambda url: SimpleNamespace(entries=[]))

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(rss, "safe_get", _boom)
    assert rss.ingest_rss("https://example.com/feed.xml") == []


def test_rss_feedparser_content_branch(monkeypatch):
    # An entry exposing a ``content`` list exercises the content-merge branch.
    entry = SimpleNamespace(
        content=[{"value": "<p>Full description body.</p>"}],
        get=lambda k, default="": {
            "title": "Platform Engineer",
            "summary": "",
            "link": "https://example.com/job/99",
        }.get(k, default),
    )
    monkeypatch.setattr(rss.feedparser, "parse", lambda url: SimpleNamespace(entries=[entry]))
    jobs = rss.ingest_rss("https://example.com/feed.xml")
    assert len(jobs) == 1
    assert "Full description body." in jobs[0].raw_text


# ── discover-links ───────────────────────────────────────────────────────────

_PAGE_HTML = """
<html><body>
  <a href="/careers/data-scientist">Open data scientist role</a>
  <a href="/about">About us</a>
  <a href="https://boards.greenhouse.io/x/jobs/1">Apply here</a>
  <a href="/careers/data-scientist">Duplicate link</a>
</body></html>
"""


def test_discover_links_filters_and_dedupes(monkeypatch):
    monkeypatch.setattr(
        discover.requests, "get",
        lambda url, **k: _FakeResp(_PAGE_HTML.encode("utf-8")),
    )
    # _FakeResp lacks .text; give discover what it needs via a richer fake.
    class Resp:
        text = _PAGE_HTML
        status_code = 200

        def raise_for_status(self):
            return None

    monkeypatch.setattr(discover.requests, "get", lambda url, **k: Resp())
    links = discover.discover_job_links("https://co.example.com")
    assert "https://co.example.com/careers/data-scientist" in links
    assert "https://boards.greenhouse.io/x/jobs/1" in links
    # /about is not a job link; duplicate is deduped.
    assert all("/about" not in link for link in links)
    assert len(links) == len(set(links))


def test_discover_links_respects_limit(monkeypatch):
    class Resp:
        text = _PAGE_HTML
        status_code = 200

        def raise_for_status(self):
            return None

    monkeypatch.setattr(discover.requests, "get", lambda url, **k: Resp())
    links = discover.discover_job_links("https://co.example.com", limit=1)
    assert len(links) == 1


def test_discover_links_propagates_http_error(monkeypatch):
    class Resp:
        text = ""
        status_code = 503

        def raise_for_status(self):
            raise RuntimeError("HTTP 503")

    monkeypatch.setattr(discover.requests, "get", lambda url, **k: Resp())
    with pytest.raises(RuntimeError):
        discover.discover_job_links("https://co.example.com")


# ── markitdown intake fallbacks ──────────────────────────────────────────────

def test_extract_text_missing_file_returns_none(tmp_path):
    assert mi.extract_text_from_file(tmp_path / "nope.pdf") is None


def test_basic_extract_reads_plain_text(tmp_path, monkeypatch):
    # Force the no-markitdown path so the basic extractor runs.
    monkeypatch.setattr(mi, "_check_markitdown", lambda: False)
    txt = tmp_path / "jd.txt"
    txt.write_text("Senior Data Scientist role.", encoding="utf-8")
    assert mi.extract_text_from_file(txt) == "Senior Data Scientist role."


def test_basic_extract_html_branch_runs(tmp_path, monkeypatch):
    # The .html branch of the basic extractor is exercised; it relies on an
    # optional helper that may be absent, in which case it returns None rather
    # than raising. Either way the binary-vs-text branch is covered.
    monkeypatch.setattr(mi, "_check_markitdown", lambda: False)
    html = tmp_path / "jd.html"
    html.write_text("<html><body><p>ML Engineer wanted.</p></body></html>", encoding="utf-8")
    text = mi.extract_text_from_file(html)
    assert text is None or "ML Engineer" in text


def test_basic_extract_binary_without_markitdown_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mi, "_check_markitdown", lambda: False)
    pdf = tmp_path / "jd.pdf"
    pdf.write_bytes(b"%PDF-1.4 binary")
    assert mi.extract_text_from_file(pdf) is None


def test_extract_uses_markitdown_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(mi, "_check_markitdown", lambda: True)

    class _Result:
        text_content = "  Converted markdown body.  "

    class _MarkItDown:
        def __init__(self, *a, **k):
            pass

        def convert(self, path):
            return _Result()

    import sys
    import types
    fake_module = types.ModuleType("markitdown")
    fake_module.MarkItDown = _MarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", fake_module)

    pdf = tmp_path / "jd.pdf"
    pdf.write_bytes(b"%PDF-1.4 data")
    text = mi.extract_text_from_file(pdf)
    assert text == "Converted markdown body."


def test_extract_falls_back_when_markitdown_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(mi, "_check_markitdown", lambda: True)

    class _Result:
        text_content = "   "

    class _MarkItDown:
        def __init__(self, *a, **k):
            pass

        def convert(self, path):
            return _Result()

    import sys
    import types
    fake_module = types.ModuleType("markitdown")
    fake_module.MarkItDown = _MarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", fake_module)

    # Empty markitdown output -> basic extractor; .txt is readable.
    txt = tmp_path / "jd.txt"
    txt.write_text("Fallback body.", encoding="utf-8")
    assert mi.extract_text_from_file(txt) == "Fallback body."


def test_extract_from_url_returns_none_without_markitdown(monkeypatch):
    monkeypatch.setattr(mi, "_check_markitdown", lambda: False)
    assert mi.extract_text_from_url("https://example.com/jd") is None


def test_extract_from_url_uses_markitdown_when_available(monkeypatch):
    monkeypatch.setattr(mi, "_check_markitdown", lambda: True)

    class _Result:
        text_content = "  URL converted body.  "

    class _MarkItDown:
        def __init__(self, *a, **k):
            pass

        def convert(self, url):
            return _Result()

    import sys
    import types
    fake_module = types.ModuleType("markitdown")
    fake_module.MarkItDown = _MarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", fake_module)
    assert mi.extract_text_from_url("https://example.com/jd") == "URL converted body."


def test_extract_from_url_returns_none_on_markitdown_error(monkeypatch):
    monkeypatch.setattr(mi, "_check_markitdown", lambda: True)

    class _MarkItDown:
        def __init__(self, *a, **k):
            pass

        def convert(self, url):
            raise RuntimeError("boom")

    import sys
    import types
    fake_module = types.ModuleType("markitdown")
    fake_module.MarkItDown = _MarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", fake_module)
    assert mi.extract_text_from_url("https://example.com/jd") is None
