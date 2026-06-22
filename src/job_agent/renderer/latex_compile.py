"""LaTeX compilation subsystem: compiler discovery, environment, intermediate
cleanup, page counting, and the ``compile_latex_to_pdf`` driver.

Imported and re-exported by :mod:`job_agent.renderer.latex_render` so existing
``from job_agent.renderer.latex_render import compile_latex_to_pdf`` paths work.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from job_agent.renderer.latex_assets import _safe_existing_file, neutralize_missing_images

logger = logging.getLogger(__name__)


class LatexCompileError(RuntimeError):
    """Raised when a LaTeX compiler exists but cannot build the PDF."""


def count_pdf_pages(pdf_path: Path) -> int | None:
    """Cheap PDF page count via ``/Type /Page`` markers (no pypdf dependency)."""
    try:
        data = pdf_path.read_bytes()
    except Exception:
        return None
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")


def _perl_available() -> bool:
    """latexmk needs a Perl interpreter; check before preferring it."""
    return shutil.which("perl") is not None


def available_latex_compiler() -> str | None:
    """Return the best available LaTeX compiler executable.

    Preference order:
    - latexmk (preferred — handles reruns/cross-refs/bibliography cleanly)
      but only when Perl is on PATH, since MiKTeX latexmk needs it.
    - pdflatex / xelatex / lualatex as direct fallbacks (no Perl needed).

    The order can be overridden by ``JOB_AGENT_LATEX_COMPILER``.
    """
    configured = os.environ.get("JOB_AGENT_LATEX_COMPILER", "").strip()
    if configured:
        configured_path = Path(configured)
        if _safe_existing_file(configured_path):
            return str(configured_path)
        found_configured = shutil.which(configured)
        if found_configured:
            return found_configured

    has_perl = _perl_available()
    order = (
        ["latexmk", "pdflatex", "xelatex", "lualatex"]
        if has_perl
        else ["pdflatex", "xelatex", "lualatex", "latexmk"]
    )
    for command in order:
        found = shutil.which(command)
        if found:
            return found
    common_roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64",
        Path(os.environ.get("PROGRAMFILES", "")) / "MiKTeX" / "miktex" / "bin" / "x64",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "MiKTeX" / "miktex" / "bin" / "x64",
        Path(os.environ.get("APPDATA", "")) / "TinyTeX" / "bin" / "windows",
        Path(os.environ.get("APPDATA", "")) / "TinyTeX" / "bin" / "win32",
    ]
    fallback_order = (
        ["latexmk.exe", "pdflatex.exe", "xelatex.exe", "lualatex.exe"]
        if has_perl
        else ["pdflatex.exe", "xelatex.exe", "lualatex.exe", "latexmk.exe"]
    )
    for root in common_roots:
        if not str(root):
            continue
        for command in fallback_order:
            candidate = root / command
            if _safe_existing_file(candidate):
                return str(candidate)
    return None


def _latex_subprocess_env() -> dict[str, str]:
    """Return an env that lets MiKTeX latexmk find Strawberry Perl."""
    env = os.environ.copy()
    path_parts = env.get("PATH", "").split(os.pathsep)
    for candidate in [Path("C:/Strawberry/perl/bin"), Path("C:/Perl64/bin"), Path("C:/Perl/bin")]:
        if candidate.exists():
            candidate_str = str(candidate)
            if not any(part.casefold() == candidate_str.casefold() for part in path_parts):
                path_parts.insert(0, candidate_str)
    env["PATH"] = os.pathsep.join(path_parts)
    return env


# LaTeX/latexmk intermediate suffixes that must not survive between compiles of
# the same jobname. ``.pdf`` is the output; ``.log`` is optionally kept for the
# user-facing error log.
_LATEX_INTERMEDIATE_SUFFIXES = (
    ".aux", ".out", ".fdb_latexmk", ".fls", ".synctex.gz",
    ".toc", ".lof", ".lot", ".bbl", ".blg", ".nav", ".snm", ".vrb", ".xdv",
)


def _clean_latex_intermediates(workdir: Path, stem: str, *, keep_log: bool = False) -> None:
    """Delete stale intermediates for ``stem`` (e.g. ``preview.aux``) in ``workdir``.

    Run before each compile so latexmk never reuses a previous run's state, and
    after a successful compile to keep the studio dir tidy.
    """
    suffixes = list(_LATEX_INTERMEDIATE_SUFFIXES)
    if not keep_log:
        suffixes.append(".log")
    for suffix in suffixes:
        try:
            (workdir / f"{stem}{suffix}").unlink(missing_ok=True)
        except Exception:
            pass


def compile_latex_to_pdf(tex_path: Path | str, output_pdf: Path | str) -> Path:
    """Compile a LaTeX file to PDF using a local compiler."""
    tex_path = Path(tex_path)
    output_pdf = Path(output_pdf)
    compiler = available_latex_compiler()
    if compiler is None:
        raise LatexCompileError("No LaTeX compiler found on PATH. Install MiKTeX or TeX Live to build cv.pdf from cv.tex.")

    workdir = tex_path.parent
    # Graceful degradation: a \photo{me.jpg} / \includegraphics whose file isn't
    # actually present (e.g. the user never imported a photo) makes pdflatex
    # abort fatally. Strip those references so the CV still builds.
    try:
        original = tex_path.read_text(encoding="utf-8")
        sanitized, dropped = neutralize_missing_images(original, workdir)
        if dropped:
            tex_path.write_text(sanitized, encoding="utf-8")
            logger.warning(
                "Omitted %d missing image(s) from %s so the CV could compile: %s",
                len(dropped), tex_path.name, ", ".join(dropped),
            )
    except OSError as exc:  # pragma: no cover - unreadable tex is handled downstream
        logger.warning("Could not pre-scan %s for missing images: %s", tex_path, exc)

    # Clear stale intermediates for THIS jobname before compiling. latexmk keys
    # its "nothing to do" decision on .fdb_latexmk/.aux; a leftover set from a
    # previous failed run (e.g. preview.*) makes it skip the rebuild or surface
    # a stale error. We always start each compile from a clean slate.
    _clean_latex_intermediates(workdir, tex_path.stem)

    if Path(compiler).name.lower().startswith("latexmk"):
        command = [compiler, "-pdf", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    else:
        command = [compiler, "-interaction=nonstopmode", "-halt-on-error", tex_path.name]

    last_result: subprocess.CompletedProcess[str] | None = None
    for _ in range(2):
        try:
            last_result = subprocess.run(
                command,
                cwd=workdir,
                env=_latex_subprocess_env(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise LatexCompileError(
                "LaTeX compilation timed out after 120 seconds. "
                "A reportlab fallback PDF will be used instead."
            ) from exc
        if last_result.returncode != 0:
            break

    built_pdf = tex_path.with_suffix(".pdf")
    if last_result is None or last_result.returncode != 0 or not built_pdf.exists():
        output = last_result.stdout if last_result else ""
        raise LatexCompileError(output[-4000:] or "LaTeX compilation failed without output.")

    if built_pdf.resolve() != output_pdf.resolve():
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built_pdf, output_pdf)
    # Clean up intermediates for this jobname (keep .log for debugging).
    _clean_latex_intermediates(workdir, tex_path.stem, keep_log=True)
    return output_pdf
