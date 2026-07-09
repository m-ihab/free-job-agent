"""Facade seam tests (G-3, docs/new/01-ENGINEERING-GUARDRAILS.md).

A facade re-exports symbols from child modules so old import paths survive a
split. The failure class these guard: code/tests reference the facade's NAME
while the runtime resolves the symbol in the CHILD's namespace — the two
silently diverge and patches stop applying. That is exactly what made
``test_latex_compile_raises_on_timeout`` pass only on machines with a real
``pdflatex``. Asserting ``facade.sym is child.sym`` makes divergence loud, and
running these with the heavy dependency absent (no pdflatex here) is the cheap
proof that a re-export still binds the same object.
"""
from __future__ import annotations


def test_latex_render_reexports_are_child_symbols():
    from job_agent.renderer import latex_assets, latex_compile, latex_helpers, latex_render

    # compile seam — the symbol behind the original latex-timeout dead-mock bug
    assert latex_render.available_latex_compiler is latex_compile.available_latex_compiler
    assert latex_render.compile_latex_to_pdf is latex_compile.compile_latex_to_pdf
    assert latex_render.count_pdf_pages is latex_compile.count_pdf_pages
    assert latex_render.LatexCompileError is latex_compile.LatexCompileError
    # text / escaping seam
    assert latex_render._escape_latex is latex_helpers._escape_latex
    assert latex_render._experience_body is latex_helpers._experience_body
    assert latex_render._is_french is latex_helpers._is_french
    # asset seam
    assert latex_render.copy_latex_assets is latex_assets.copy_latex_assets
    assert latex_render.neutralize_missing_images is latex_assets.neutralize_missing_images


def test_database_methods_resolve_to_their_mixins():
    from job_agent.db.database import Database
    from job_agent.db.database_boards import BoardsMixin
    from job_agent.db.database_conversion import ConversionMixin
    from job_agent.db.database_embeddings import EmbeddingsMixin
    from job_agent.db.database_jobs import JobsMixin
    from job_agent.db.database_meta import MetaMixin
    from job_agent.db.database_packets import PacketsMixin
    from job_agent.db.database_stories import StoriesMixin

    for mixin in (JobsMixin, PacketsMixin, MetaMixin, ConversionMixin,
                  EmbeddingsMixin, StoriesMixin, BoardsMixin):
        assert issubclass(Database, mixin)

    # representative method identity — the facade must not shadow a mixin method
    assert Database.save_job is JobsMixin.save_job
    assert Database.get_job is JobsMixin.get_job


def test_route_registries_point_at_real_handlers():
    from job_agent.ui.routes import GET_ROUTES, POST_ROUTES, get_core

    assert GET_ROUTES["/api/state"] is get_core.get_state
    # every registered handler is a live callable — a broken re-export would be
    # None or a stale name, caught here at import time not on first request.
    for path, handler in {**GET_ROUTES, **POST_ROUTES}.items():
        assert callable(handler), f"route {path} maps to non-callable {handler!r}"
