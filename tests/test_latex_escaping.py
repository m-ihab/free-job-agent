"""Adversarial LaTeX escaping + deterministic render tests.

These tests assert that user/job-supplied text containing LaTeX metacharacters
is neutralised by ``_escape_latex`` / ``_inline_latex`` and that the public
render helpers (set_cvlang / detect_cvlang / compact_cv_source /
render_latex_source / render_moderncv_template) behave deterministically. No
real LaTeX compiler is invoked.
"""
from __future__ import annotations


import pytest

from job_agent.renderer.latex_helpers import (
    _clean_role_phrase,
    _date_range,
    _detect_contract_family,
    _escape_latex,
    _experience_body,
    _github_handle,
    _inline_latex,
    _is_french,
    _linkedin_handle,
    _project_body,
    _tailored_summary,
)
from job_agent.schemas.candidate import Project, WorkExperience
from job_agent.renderer.latex_render import (
    LatexCompileError,
    compact_cv_source,
    compile_latex_to_pdf,
    detect_cvlang,
    render_latex_source,
    render_moderncv_template,
    set_cvlang,
)


# --- Adversarial escaping -------------------------------------------------


def test_escape_latex_neutralises_backslash_and_braces():
    # Arrange: an injection attempt with \input{} and grouping braces.
    payload = r"\input{/etc/passwd}"

    # Act
    escaped = _escape_latex(payload)

    # Assert: no raw control sequence survives.
    assert r"\input" not in escaped
    assert r"\textbackslash{}" in escaped
    assert escaped.count(r"\{") == 1
    assert escaped.count(r"\}") == 1


@pytest.mark.parametrize(
    "char,expected",
    [
        ("%", r"\%"),
        ("$", r"\$"),
        ("&", r"\&"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ],
)
def test_escape_latex_handles_each_metacharacter(char, expected):
    # Act
    escaped = _escape_latex(f"a{char}b")

    # Assert
    assert escaped == f"a{expected}b"


def test_escape_latex_double_backslash_is_fully_escaped():
    # Arrange: a literal double backslash (line break injection attempt).
    escaped = _escape_latex("line\\\\break")

    # Assert: two textbackslash macros, no raw "\\" sequence remains.
    assert escaped.count(r"\textbackslash{}") == 2
    assert "\\\\" not in escaped.replace(r"\textbackslash{}", "")


def test_inline_latex_escapes_metachars_but_keeps_markdown_bold():
    # Arrange: bold markdown plus an ampersand that must be escaped.
    text = "**Python & SQL**"

    # Act
    result = _inline_latex(text)

    # Assert: ampersand escaped, bold converted to \textbf, no raw &.
    assert r"\&" in result
    assert r"\textbf{" in result
    assert "Python & SQL" not in result


def test_inline_latex_drops_markdown_link_target():
    # Arrange
    text = "[my repo](https://example.com/x_y)"

    # Act
    result = _inline_latex(text)

    # Assert: visible text kept, URL (with its underscore) dropped.
    assert "my repo" in result
    assert "https://example.com" not in result


# --- set_cvlang / detect_cvlang ------------------------------------------


def test_detect_cvlang_defaults_to_en_without_toggle():
    assert detect_cvlang("no toggle here") == "en"


def test_set_cvlang_switches_to_fr_and_detect_reads_it_back():
    # Arrange
    source = r"\newcommand{\cvlang}{en}" + "\nbody"

    # Act
    switched = set_cvlang(source, "fr")

    # Assert
    assert detect_cvlang(switched) == "fr"


def test_set_cvlang_ignores_unknown_language():
    source = r"\newcommand{\cvlang}{en}"
    assert set_cvlang(source, "de") == source


def test_set_cvlang_no_op_when_no_toggle_present():
    source = "plain text"
    assert set_cvlang(source, "fr") == source


# --- compact_cv_source ----------------------------------------------------


def test_compact_cv_source_level1_is_typography_only():
    # Arrange
    source = r"\documentclass[11pt,a4paper]{moderncv}" + "\ntop=1.2cm, bottom=1.2cm"

    # Act
    out = compact_cv_source(source, 1)

    # Assert: font shrunk and margins tightened, no itemize trim at level 1.
    assert "10pt" in out
    assert "top=0.8cm, bottom=0.8cm" in out


def test_compact_cv_source_level2_caps_itemize_to_three():
    # Arrange: an itemize block with five items.
    items = "".join(rf"\item item{i}" for i in range(5))
    source = r"\begin{itemize}" + items + r"\end{itemize}"

    # Act
    out = compact_cv_source(source, 2)

    # Assert: only three items remain.
    assert out.count(r"\item") == 3


# --- render_latex_source (markdown fallback path) ------------------------


def test_render_latex_source_builds_valid_article_document():
    # Arrange
    markdown = "# Jane Doe\n\n## Experience\n\n- Built **APIs** with FastAPI\n"

    # Act
    tex = render_latex_source(markdown, title="My CV")

    # Assert: a complete document with the bullet rendered as an itemize item.
    assert r"\begin{document}" in tex
    assert r"\end{document}" in tex
    assert r"\section*{Experience}" in tex
    assert r"\item" in tex
    assert r"\textbf{APIs}" in tex


def test_render_latex_source_escapes_title_metacharacters():
    # Act
    tex = render_latex_source("# Heading", title="100% CV & Notes")

    # Assert
    assert r"\title{100\% CV \& Notes}" in tex


# --- render_moderncv_template --------------------------------------------


def test_render_moderncv_template_injects_contact_and_header(tmp_path, sample_job, sample_master_cv, sample_profile):
    # Arrange: a minimal moderncv template carrying the placeholders we rewrite.
    template = tmp_path / "main.tex"
    template.write_text(
        "\n".join([
            r"\newcommand{\cvlang}{en}",
            r"\name{Old}{Name}",
            r"\address{Old City}{}{}",
            r"\phone[mobile]{000}",
            r"\email{old@example.com}",
            r"\begin{document}",
            r"\end{document}",
        ]),
        encoding="utf-8",
    )

    # Act
    rendered = render_moderncv_template(
        template, job=sample_job, master_cv=sample_master_cv,
        profile=sample_profile, language="fr",
    )

    # Assert: header comment, the candidate email swapped in, language forced.
    assert "Tailored by free-job-agent" in rendered
    assert sample_master_cv.contact.email in rendered
    assert detect_cvlang(rendered) == "fr"


# --- pure latex_helpers ---------------------------------------------------


def test_date_range_formats_year_month_and_present():
    assert _date_range("2024-01", "2024-06") == "January 2024 -- June 2024"
    assert _date_range("2025-03", None) == "March 2025 -- Present"


def test_linkedin_and_github_handles_extracted_from_urls():
    assert _linkedin_handle("https://linkedin.com/in/jane-doe/") == "jane-doe"
    assert _github_handle("https://github.com/jane-doe") == "jane-doe"
    assert _linkedin_handle(None) == ""


def test_is_french_detects_accents_and_stage_terms():
    assert _is_french("Recherche un stage en données") is True
    assert _is_french("Looking for a role") is False


def test_clean_role_phrase_maps_french_title_to_english_label():
    assert _clean_role_phrase("Ingénieur ML et Data scientist (H/F)") == "Data Scientist"
    assert _clean_role_phrase("Stage Data Engineer Paris") == "Data Engineer"


def test_detect_contract_family_prioritises_alternance(sample_job):
    alt = sample_job.copy(update={"title": "Alternance Data Scientist (stage possible)"})
    assert _detect_contract_family(alt) == "alternance"
    stage = sample_job.copy(update={"title": "Stage Data Scientist"})
    assert _detect_contract_family(stage) == "stage"


def test_experience_body_ranks_bullets_and_appends_technologies(sample_job):
    exp = WorkExperience(
        company="ACME", title="Data Intern", start_date="2025-01", end_date="2025-06",
        bullet_points=["Wrote docs", "Built FastAPI services with PostgreSQL"],
        technologies=["Python", "FastAPI"],
    )
    body = _experience_body(exp, sample_job)
    # The job-relevant bullet (FastAPI/PostgreSQL) is ranked above the doc one.
    assert body.index("FastAPI services") < body.index("Wrote docs")
    assert "Technologies: Python, FastAPI" in body


def test_project_body_escapes_name_and_includes_stack(sample_job):
    project = Project(
        name="ML & Ops",
        description="A model service",
        technologies=["Docker", "FastAPI"],
        bullet_points=["Shipped to production"],
    )
    body = _project_body(project, sample_job)
    assert r"\&" in body  # ampersand in name escaped
    assert "Technologies: Docker, FastAPI" in body


def test_tailored_summary_appends_contract_aware_closing(sample_job, sample_master_cv, sample_profile):
    # Arrange: an English stage listing.
    job = sample_job.copy(update={"title": "Data Science Internship", "company": "ACME"})

    # Act
    summary = _tailored_summary(
        job, sample_master_cv, sample_profile,
        original_body="Curated profile narrative", french=False,
    )

    # Assert: the curated body is preserved and an internship closer added.
    assert summary.startswith("Curated profile narrative")
    assert "internship" in summary.lower()


# --- compile_latex_to_pdf no-compiler error path -------------------------


def test_compile_latex_to_pdf_raises_when_no_compiler(tmp_path, monkeypatch):
    # Arrange: force "no compiler found".
    monkeypatch.setattr(
        "job_agent.renderer.latex_compile.available_latex_compiler",
        lambda: None,
    )
    tex_path = tmp_path / "cv.tex"
    tex_path.write_text(r"\documentclass{article}\begin{document}x\end{document}", encoding="utf-8")

    # Act / Assert
    with pytest.raises(LatexCompileError):
        compile_latex_to_pdf(tex_path, tmp_path / "cv.pdf")
