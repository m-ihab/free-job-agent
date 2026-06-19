"""Regression tests for bugs surfaced during the WP-9 coverage work.

Each test pins the *corrected* behaviour so the fix cannot silently regress.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from job_agent.generator.interview_prep import _best_project, generate_interview_prep
from job_agent.intake.markitdown_intake import _basic_text_extract
from job_agent.schemas.job import JobListing


def test_best_project_returns_dict_on_no_tech_match(sample_master_cv):
    """_best_project's no-overlap fallback must return a dict, not the raw
    Project model — callers index it with .get()."""
    job = JobListing(title="COBOL Dev", company="X", source="paste",
                     raw_text="x", tech_stack=["cobol", "fortran"])
    result = _best_project(sample_master_cv, job)
    assert isinstance(result, dict)


def test_generate_interview_prep_does_not_crash_on_unmatched_tech(
    sample_job, sample_master_cv, sample_profile
):
    """Previously raised AttributeError('Project' object has no attribute 'get')
    when no project's tech overlapped the job."""
    job = JobListing(title="Mainframe Engineer", company="ACME", source="paste",
                     raw_text="x", tech_stack=["cobol", "fortran", "assembler"])
    md = generate_interview_prep(job, sample_master_cv, sample_profile)
    assert isinstance(md, str) and len(md) > 0


def test_rss_xml_fallback_parses_title(monkeypatch):
    """The ElementTree-truthiness fix: a text-only <title> must be parsed, not
    dropped to the '[To Be Parsed]' placeholder."""
    xml = (
        b"<?xml version='1.0'?><rss><channel>"
        b"<item><title>Senior Data Scientist</title>"
        b"<description>Great role</description>"
        b"<link>https://example.com/job/1</link></item>"
        b"</channel></rss>"
    )

    class _Resp:
        content = xml

        def raise_for_status(self):
            return None

    from job_agent.intake import rss
    monkeypatch.setattr(rss, "safe_get", lambda *a, **k: _Resp())
    jobs = rss._ingest_rss_fallback("https://example.com/feed")
    assert len(jobs) == 1
    assert jobs[0].title == "Senior Data Scientist"
    assert jobs[0].source == "rss"


def test_markitdown_html_fallback_strips_tags(tmp_path: Path):
    """The .html fallback now uses the real strip_html helper (not a missing
    extract_text), so it returns visible text instead of silently None."""
    html = tmp_path / "job.html"
    html.write_text("<html><body><h1>Data Scientist</h1><p>Paris</p></body></html>", encoding="utf-8")
    with patch("job_agent.intake.markitdown_intake._check_markitdown", return_value=False):
        text = _basic_text_extract(html)
    assert text is not None
    assert "Data Scientist" in text
