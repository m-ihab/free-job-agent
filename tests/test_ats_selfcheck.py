"""Tests for the local ATS-parse self-check (G1)."""
from __future__ import annotations

import io

import pytest

from job_agent.generator.ats_selfcheck import (
    GRADE_POOR,
    _job_keywords,
    extract_pdf_text,
    run_ats_selfcheck,
)
from job_agent.schemas.job import JobListing


def _make_pdf(text_lines: list[str]) -> bytes:
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in text_lines:
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


def _job(**kw) -> JobListing:
    base = dict(
        title="Data Scientist",
        company="ACME",
        location="Paris",
        description="d",
        source="paste",
        raw_text="r",
        tech_stack=["Python", "PyTorch", "SQL"],
        requirements=[
            "Machine learning",
            "3+ years experience building production ML systems and pipelines.",
        ],
    )
    base.update(kw)
    return JobListing(**base)


def test_extract_pdf_text_reads_reportlab_pdf():
    pdf = _make_pdf(["Hello Python world", "PyTorch and SQL"])
    text = extract_pdf_text(pdf)
    assert "Python" in text and "PyTorch" in text and "SQL" in text


def test_run_selfcheck_full_coverage_good_grade(tmp_path):
    lines = ["John Doe - Data Scientist"] + ["Skilled in Python, PyTorch, SQL and machine learning."] * 12
    cv_md = "\n".join(lines)
    p = tmp_path / "cv.pdf"
    p.write_bytes(_make_pdf(lines))
    report = run_ats_selfcheck(_job(), cv_md, p)
    assert set(report.keywords_found_in_pdf) >= {"Python", "PyTorch", "SQL", "Machine learning"}
    assert report.keyword_coverage == 1.0
    assert report.keywords_missing_in_pdf == []
    assert report.pdf_readable


def test_missing_keyword_detected(tmp_path):
    lines = ["Data Scientist bio"] + ["Experienced with Python and SQL."] * 12
    cv_md = "\n".join(lines)  # no PyTorch anywhere
    p = tmp_path / "cv.pdf"
    p.write_bytes(_make_pdf(lines))
    report = run_ats_selfcheck(_job(), cv_md, p)
    assert "PyTorch" in report.keywords_missing_in_pdf
    assert "PyTorch" not in report.keywords_lost_in_render  # absent from cv.md too


def test_lost_in_render_when_in_cv_but_not_pdf(tmp_path):
    # cv.md mentions PyTorch, but the rendered PDF omits it → render/encoding loss.
    cv_md = "Data scientist. Python PyTorch SQL machine learning. " * 10
    p = tmp_path / "cv.pdf"
    p.write_bytes(_make_pdf(["Data Scientist"] + ["Python and SQL only here."] * 12))
    report = run_ats_selfcheck(_job(), cv_md, p)
    assert "PyTorch" in report.keywords_lost_in_render
    assert "PyTorch" in report.keywords_missing_in_pdf


def test_unreadable_pdf_is_poor_and_fail_closed(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"%PDF-1.4 not a real pdf body")
    report = run_ats_selfcheck(_job(), "Python PyTorch SQL", p)
    assert report.parse_grade == GRADE_POOR
    assert not report.pdf_readable


def test_missing_file_never_raises(tmp_path):
    report = run_ats_selfcheck(_job(), "Python", tmp_path / "nope.pdf")
    assert report.parse_grade == GRADE_POOR
    assert report.char_count == 0


def test_job_keywords_filters_sentence_requirements():
    kws = _job_keywords(_job())
    assert "Python" in kws and "Machine learning" in kws
    assert all("years experience" not in k for k in kws)


def test_report_serialization(tmp_path):
    p = tmp_path / "cv.pdf"
    p.write_bytes(_make_pdf(["Data Scientist"] + ["Python PyTorch SQL machine learning"] * 12))
    report = run_ats_selfcheck(_job(), "Python PyTorch SQL machine learning", p)
    d = report.to_dict()
    assert d["parse_grade"] in {"good", "partial", "poor"}
    assert 0.0 <= d["keyword_coverage"] <= 1.0
    assert "ATS parse self-check" in report.to_markdown()


def test_extract_handles_garbage_without_raising():
    assert extract_pdf_text(b"\x00\x01\x02 random bytes no streams") == ""


def test_no_keywords_is_full_coverage(tmp_path):
    p = tmp_path / "cv.pdf"
    p.write_bytes(_make_pdf(["Some text here"] * 12))
    job = _job(tech_stack=[], requirements=["This is a full sentence requirement."])
    report = run_ats_selfcheck(job, "text", p)
    assert report.keyword_coverage == 1.0
    assert report.keywords_checked == []
