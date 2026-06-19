"""Behavioral lock for the two functions rewritten to drop PEP-701-only f-strings.

These guard the *output*, so a future re-inlining that reintroduces the 3.11
break (or changes the rendered markup) is caught by behavior, not just grammar.
"""
from __future__ import annotations

from job_agent.portfolio_builder import _section_card_html
from job_agent.renderer.latex_render import render_latex_source


def test_section_card_html_includes_small_when_meta_present() -> None:
    html_out = _section_card_html([{"title": "Role", "detail": "Did things", "meta": "2024"}], 0)
    assert '<small class="muted">2024</small>' in html_out
    assert "<h3>Role</h3>" in html_out


def test_section_card_html_omits_small_when_meta_absent() -> None:
    html_out = _section_card_html([{"title": "Role", "detail": "Did things"}], 0)
    assert "<small" not in html_out
    assert "<h3>Role</h3>" in html_out


def test_render_latex_source_emits_escaped_list_items() -> None:
    md = "## Experience\n- Built models & ML_pipelines (90% uptime)\n- Shipped v2"
    tex = render_latex_source(md, title="CV")
    assert r"\begin{itemize}" in tex and r"\end{itemize}" in tex
    assert r"\item" in tex
    # LaTeX specials from the bullet text must be escaped, not passed through raw.
    assert r"\&" in tex
    assert r"\_" in tex
    assert r"\%" in tex
