"""Render tailored CV markdown to LaTeX and optionally compile it."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


class LatexCompileError(RuntimeError):
    """Raised when a LaTeX compiler exists but cannot build the PDF."""


def _escape_latex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _inline_latex(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    escaped = _escape_latex(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\\textit{\1}", escaped)
    return escaped


def render_latex_source(markdown_content: str, title: str = "Tailored CV") -> str:
    """Convert the generated CV markdown into editable LaTeX source."""
    body: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            body.append(r"\end{itemize}")
            in_list = False

    for raw_line in markdown_content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("<!--"):
            close_list()
            if body and body[-1] != "":
                body.append("")
            continue
        if line.startswith("# "):
            close_list()
            body.append(rf"\begin{{center}}\LARGE\textbf{{{_inline_latex(line[2:])}}}\end{{center}}")
        elif line.startswith("## "):
            close_list()
            body.append(rf"\section*{{{_inline_latex(line[3:])}}}")
        elif line.startswith("### "):
            close_list()
            body.append(rf"\subsection*{{{_inline_latex(line[4:])}}}")
        elif re.match(r"^[-*]\s+", line):
            if not in_list:
                body.append(r"\begin{itemize}")
                in_list = True
            body.append(rf"\item {_inline_latex(re.sub(r'^[-*]\s+', '', line))}")
        else:
            close_list()
            body.append(_inline_latex(line) + r"\\")
    close_list()

    return "\n".join(
        [
            r"\documentclass[11pt,a4paper]{article}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage[margin=1.45cm]{geometry}",
            r"\usepackage[hidelinks]{hyperref}",
            r"\usepackage{enumitem}",
            r"\setlist[itemize]{leftmargin=*, itemsep=0.15em, topsep=0.2em}",
            r"\setlength{\parindent}{0pt}",
            r"\setlength{\parskip}{0.35em}",
            rf"\title{{{_escape_latex(title)}}}",
            r"\date{}",
            r"\begin{document}",
            *body,
            r"\end{document}",
            "",
        ]
    )


def available_latex_compiler() -> str | None:
    """Return the best available LaTeX compiler executable."""
    for command in ["latexmk", "pdflatex", "xelatex", "lualatex"]:
        found = shutil.which(command)
        if found:
            return found
    return None


def compile_latex_to_pdf(tex_path: Path | str, output_pdf: Path | str) -> Path:
    """Compile a LaTeX file to PDF using a local compiler."""
    tex_path = Path(tex_path)
    output_pdf = Path(output_pdf)
    compiler = available_latex_compiler()
    if compiler is None:
        raise LatexCompileError("No LaTeX compiler found on PATH. Install MiKTeX or TeX Live to build cv.pdf from cv.tex.")

    workdir = tex_path.parent
    if Path(compiler).name.lower().startswith("latexmk"):
        command = [compiler, "-pdf", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    else:
        command = [compiler, "-interaction=nonstopmode", "-halt-on-error", tex_path.name]

    last_result: subprocess.CompletedProcess[str] | None = None
    for _ in range(2):
        last_result = subprocess.run(
            command,
            cwd=workdir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if last_result.returncode != 0:
            break

    built_pdf = tex_path.with_suffix(".pdf")
    if last_result is None or last_result.returncode != 0 or not built_pdf.exists():
        output = last_result.stdout if last_result else ""
        raise LatexCompileError(output[-4000:] or "LaTeX compilation failed without output.")

    if built_pdf.resolve() != output_pdf.resolve():
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built_pdf, output_pdf)
    return output_pdf
