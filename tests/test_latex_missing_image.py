r"""Regression: a missing CV photo must not fatally abort LaTeX compilation.

Repro: the moderncv template carries ``\photo{me.jpg}``, but a user who never
imported a photo has no me.jpg, so pdflatex aborts with
"reading image file failed". The renderer now drops references to images that
aren't present beside the .tex, so the CV still builds (just without the photo).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.renderer import latex_compile, latex_render  # noqa: F401  (latex_render kept for re-export check)
from job_agent.renderer.latex_render import (
    LatexCompileError,
    _image_present,
    compile_latex_to_pdf,
    neutralize_missing_images,
)


def test_missing_photo_is_dropped(tmp_path: Path) -> None:
    tex = r"\photo[64pt][0.4pt]{me.jpg}" + "\n" + r"\section{X}"
    out, dropped = neutralize_missing_images(tex, tmp_path)
    assert dropped == ["me.jpg"]
    assert r"\photo" not in out
    assert r"\section{X}" in out  # surrounding content untouched


def test_present_photo_is_kept(tmp_path: Path) -> None:
    (tmp_path / "me.jpg").write_bytes(b"\xff\xd8\xff")  # any bytes; presence is what matters
    tex = r"\photo[64pt][0.4pt]{me.jpg}"
    out, dropped = neutralize_missing_images(tex, tmp_path)
    assert dropped == []
    assert out == tex


def test_extensionless_reference_resolves_image(tmp_path: Path) -> None:
    (tmp_path / "me.png").write_bytes(b"x")
    # \photo{me} should resolve me.png and be kept.
    assert _image_present("me", tmp_path) is True
    assert _image_present("missing", tmp_path) is False


def test_inline_includegraphics_removed_without_breaking_braces(tmp_path: Path) -> None:
    tex = r"\raisebox{0pt}{\includegraphics[width=2cm]{logo}}"
    out, dropped = neutralize_missing_images(tex, tmp_path)
    assert dropped == ["logo"]
    assert out == r"\raisebox{0pt}{}"  # no stray/commented braces


def test_compile_strips_missing_image_before_running(tmp_path: Path, monkeypatch) -> None:
    tex_path = tmp_path / "preview.tex"
    tex_path.write_text(
        r"\documentclass{article}\photo{me.jpg}\begin{document}hi\end{document}",
        encoding="utf-8",
    )
    monkeypatch.setattr(latex_compile, "available_latex_compiler", lambda: "pdflatex")

    seen: dict = {}

    def fake_run(command, **kwargs):  # noqa: ANN001
        # The tex handed to the compiler must already have me.jpg stripped.
        seen["tex"] = tex_path.read_text(encoding="utf-8")
        (tmp_path / "preview.pdf").write_bytes(b"%PDF-1.4")
        return __import__("subprocess").CompletedProcess(command, 0, stdout="ok")

    monkeypatch.setattr(latex_compile.subprocess, "run", fake_run)
    out_pdf = compile_latex_to_pdf(tex_path, tmp_path / "out.pdf")
    assert out_pdf.exists()
    assert "me.jpg" not in seen["tex"]
    assert r"\photo" not in seen["tex"]


def test_compile_keeps_present_image(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "me.jpg").write_bytes(b"\xff\xd8\xff")
    tex_path = tmp_path / "preview.tex"
    tex_path.write_text(
        r"\documentclass{article}\photo{me.jpg}\begin{document}hi\end{document}",
        encoding="utf-8",
    )
    monkeypatch.setattr(latex_compile, "available_latex_compiler", lambda: "pdflatex")

    def fake_run(command, **kwargs):  # noqa: ANN001
        (tmp_path / "preview.pdf").write_bytes(b"%PDF-1.4")
        return __import__("subprocess").CompletedProcess(command, 0, stdout="ok")

    monkeypatch.setattr(latex_compile.subprocess, "run", fake_run)
    compile_latex_to_pdf(tex_path, tmp_path / "out.pdf")
    assert r"\photo{me.jpg}" in tex_path.read_text(encoding="utf-8")  # untouched


def test_no_compiler_still_raises(tmp_path: Path, monkeypatch) -> None:
    tex_path = tmp_path / "preview.tex"
    tex_path.write_text(r"\documentclass{article}\begin{document}hi\end{document}", encoding="utf-8")
    monkeypatch.setattr(latex_compile, "available_latex_compiler", lambda: None)
    with pytest.raises(LatexCompileError):
        compile_latex_to_pdf(tex_path, tmp_path / "out.pdf")
