"""Guards the declared `requires-python = ">=3.11"` contract.

The dev venv runs 3.12, whose grammar silently accepts PEP 701 f-strings
(backslashes / nested quotes inside f-string expressions). Those are hard
SyntaxErrors on 3.11. `ast.parse(..., feature_version=(3, 11))` pins the parser
to the 3.11 grammar regardless of the running interpreter, so this test fails
on exactly the constructs that would break a real 3.11 install.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
PY_FILES = sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(SRC)))
def test_module_parses_under_python_311_grammar(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(path), feature_version=(3, 11))
    except SyntaxError as exc:  # pragma: no cover - failure path
        pytest.fail(f"{path} uses syntax invalid on Python 3.11: {exc}")
