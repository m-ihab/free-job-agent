"""Tests for the renderer modules."""
import pytest

from job_agent.renderer.html_render import render_html
from job_agent.renderer.markdown_render import render_markdown
from job_agent.renderer.pdf_render import render_pdf

SAMPLE_MD = """# Alex Chen

alex@example.com | +1-555-0100

## Summary

Senior engineer with 7 years experience.

## Experience

### Senior Engineer — DataStream Inc.
*2020 – Present*

- Built real-time pipeline
- Mentored junior engineers

## Skills

**language:** Python, Go
"""


def test_render_markdown_passthrough():
    result = render_markdown(SAMPLE_MD)
    assert result == SAMPLE_MD


def test_render_html_returns_string():
    result = render_html(SAMPLE_MD)
    assert isinstance(result, str)
    assert len(result) > 0


def test_render_html_is_complete_html():
    result = render_html(SAMPLE_MD)
    assert "<!DOCTYPE html>" in result
    assert "<html" in result
    assert "</html>" in result
    assert "<body>" in result
    assert "</body>" in result


def test_render_html_contains_title():
    result = render_html(SAMPLE_MD, title="My Document")
    assert "My Document" in result


def test_render_html_contains_headings():
    result = render_html(SAMPLE_MD)
    assert "<h1>" in result
    assert "<h2>" in result
    assert "<h3>" in result


def test_render_html_contains_list_items():
    result = render_html(SAMPLE_MD)
    assert "<li>" in result
    assert "<ul>" in result


def test_render_pdf_creates_file(tmp_path):
    output = tmp_path / "test_output.pdf"
    result_path = render_pdf(SAMPLE_MD, output, title="Test CV")
    assert result_path == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_render_pdf_returns_path(tmp_path):
    output = tmp_path / "cv.pdf"
    result = render_pdf(SAMPLE_MD, output)
    assert str(result) == str(output)


def test_render_pdf_creates_parent_dirs(tmp_path):
    output = tmp_path / "subdir" / "nested" / "cv.pdf"
    render_pdf(SAMPLE_MD, output)
    assert output.exists()
