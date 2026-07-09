"""Local ATS-parse self-check (G1) — no third-party deps, no UI imports.

After a tailored CV is rendered to PDF, this re-reads that PDF the way a naive
ATS would: it pulls the text layer using only the standard library (zlib +
ASCII85), then checks whether the keywords we meant to surface actually survive
into machine-readable text. Two distinct signals fall out:

* ``keywords_missing_in_pdf`` — job keywords absent from the PDF text at all
  (a plain coverage gap the tailoring should close).
* ``keywords_lost_in_render`` — keywords that ARE in the ``cv.md`` source but are
  NOT readable in the rendered PDF. That gap is an encoding/rendering loss
  (custom fonts, ligatures, text-as-image) — the CV *says* the right thing but a
  keyword-matching ATS can't see it.

If our own permissive parser cannot read the PDF at all, a strict ATS is in worse
shape, so a poor parse ratio is itself the warning. This module is a deliberate
library seam (money-engine's CandidatPro imports :func:`run_ats_selfcheck`): keep
it dependency-free and free of UI/pipeline imports.
"""
from __future__ import annotations

import base64
import re
import zlib
from dataclasses import dataclass
from pathlib import Path

from job_agent.schemas.job import JobListing

GRADE_GOOD = "good"
GRADE_PARTIAL = "partial"
GRADE_POOR = "poor"

# Below this many extracted characters we treat the PDF as effectively unreadable
# (a title-only or image-only render), regardless of the ratio.
_MIN_READABLE_CHARS = 120

# Capture the stream body up to `endstream`. reportlab ends ASCII85 bodies with
# `~>endstream` (no separating EOL), so we must NOT require a newline before
# `endstream`; _decompress_stream strips the trailing EOL/`~>` itself.
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)endstream", re.DOTALL)
_LITERAL_RE = re.compile(rb"\((?:\\.|[^\\()])*\)", re.DOTALL)
_HEX_RE = re.compile(rb"<([0-9A-Fa-f\s]+)>")
_PDF_ESCAPES = {
    b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b",
    b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\",
}


@dataclass(frozen=True)
class SelfCheckReport:
    """Result of re-parsing a rendered CV PDF for ATS readability."""

    parse_ratio: float
    parse_grade: str
    pdf_readable: bool
    char_count: int
    keyword_coverage: float
    keywords_checked: list[str]
    keywords_found_in_pdf: list[str]
    keywords_missing_in_pdf: list[str]
    keywords_lost_in_render: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "parse_ratio": round(self.parse_ratio, 3),
            "parse_grade": self.parse_grade,
            "pdf_readable": self.pdf_readable,
            "char_count": self.char_count,
            "keyword_coverage": round(self.keyword_coverage, 3),
            "keywords_checked": self.keywords_checked,
            "keywords_found_in_pdf": self.keywords_found_in_pdf,
            "keywords_missing_in_pdf": self.keywords_missing_in_pdf,
            "keywords_lost_in_render": self.keywords_lost_in_render,
        }

    def to_markdown(self) -> str:
        pct = f"{self.keyword_coverage * 100:.0f}%"
        lines = [
            "# ATS parse self-check",
            "",
            f"- **Parse grade:** {self.parse_grade} (ratio {self.parse_ratio:.2f}, "
            f"{self.char_count} readable chars)",
            f"- **Keyword coverage:** {pct} "
            f"({len(self.keywords_found_in_pdf)}/{len(self.keywords_checked)} keywords readable in the PDF)",
        ]
        if self.keywords_missing_in_pdf:
            lines.append(f"- **Missing from PDF:** {', '.join(self.keywords_missing_in_pdf)}")
        if self.keywords_lost_in_render:
            lines.append(
                "- **⚠ Lost in render** (in cv.md but unreadable in the PDF — likely a "
                f"font/encoding issue): {', '.join(self.keywords_lost_in_render)}"
            )
        if self.parse_grade == GRADE_POOR:
            lines.append(
                "- **⚠ Poor parse:** our permissive reader could barely extract text; a "
                "strict keyword ATS may read even less. Check fonts/embedding."
            )
        return "\n".join(lines) + "\n"


def _unescape_pdf_literal(raw: bytes) -> str:
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i : i + 1]
        if ch == b"\\" and i + 1 < n:
            nxt = raw[i + 1 : i + 2]
            if nxt in _PDF_ESCAPES:
                out += _PDF_ESCAPES[nxt]
                i += 2
                continue
            if nxt.isdigit():  # octal \ddd (1–3 digits)
                j = i + 1
                while j < n and j < i + 4 and raw[j : j + 1].isdigit():
                    j += 1
                try:
                    out.append(int(raw[i + 1 : j], 8) & 0xFF)
                except ValueError:
                    pass
                i = j
                continue
            out += nxt  # unknown escape → drop the backslash
            i += 2
            continue
        out += ch
        i += 1
    return out.decode("latin-1", errors="replace")


def _decompress_stream(raw: bytes) -> bytes | None:
    """Best-effort decode of a PDF stream body: Flate, ASCII85+Flate (reportlab's
    default chain), or an already-plain content stream."""
    try:
        return zlib.decompress(raw)
    except zlib.error:
        pass
    stripped = raw.strip()
    if stripped.endswith(b"~>"):
        stripped = stripped[:-2]
    if stripped.startswith(b"<~"):
        stripped = stripped[2:]
    try:
        a85 = base64.a85decode(stripped)
        try:
            return zlib.decompress(a85)
        except zlib.error:
            return a85
    except (ValueError, zlib.error):
        pass
    if b"Tj" in raw or b"TJ" in raw:  # uncompressed content stream
        return raw
    return None


def _strings_from_content(content: bytes) -> list[str]:
    out: list[str] = []
    for match in _LITERAL_RE.finditer(content):
        out.append(_unescape_pdf_literal(match.group()[1:-1]))
    for match in _HEX_RE.finditer(content):
        hexs = re.sub(rb"\s", b"", match.group(1))
        if len(hexs) % 2 == 0 and hexs:
            try:
                out.append(bytes.fromhex(hexs.decode("ascii")).decode("latin-1", errors="replace"))
            except ValueError:
                continue
    return out


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract the readable text layer from PDF bytes with stdlib only."""
    parts: list[str] = []
    for match in _STREAM_RE.finditer(pdf_bytes):
        content = _decompress_stream(match.group(1))
        if content is None:
            continue
        parts.extend(_strings_from_content(content))
    return " ".join(p for p in parts if p.strip())


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def _job_keywords(job: JobListing) -> list[str]:
    """Keywords an ATS would scan for: the tech stack plus short, skill-like
    requirements. Full-sentence requirements are filtered — they are prose, not
    keywords, and would produce noisy 'missing' hits."""
    candidates: list[str] = [str(t).strip() for t in (getattr(job, "tech_stack", None) or [])]
    for req in getattr(job, "requirements", None) or []:
        text = str(req).strip()
        if text and len(text.split()) <= 4 and not text.endswith("."):
            candidates.append(text)
    seen: set[str] = set()
    keywords: list[str] = []
    for kw in candidates:
        key = kw.casefold()
        if kw and key not in seen:
            seen.add(key)
            keywords.append(kw)
    return keywords


def _grade(parse_ratio: float, pdf_readable: bool) -> str:
    if not pdf_readable:
        return GRADE_POOR
    if parse_ratio >= 0.5:
        return GRADE_GOOD
    if parse_ratio >= 0.2:
        return GRADE_PARTIAL
    return GRADE_POOR


def run_ats_selfcheck(job: JobListing, cv_md: str, pdf_path: str | Path) -> SelfCheckReport:
    """Re-parse a rendered CV PDF and report ATS keyword readability.

    Never raises: an unreadable/missing PDF yields a POOR grade (fail-closed —
    the inability to read is the finding).
    """
    try:
        pdf_bytes = Path(pdf_path).read_bytes()
    except OSError:
        pdf_bytes = b""

    pdf_text = extract_pdf_text(pdf_bytes) if pdf_bytes else ""
    pdf_norm = _norm(pdf_text)
    cv_norm = _norm(cv_md or "")
    char_count = len(pdf_text)
    pdf_readable = char_count >= _MIN_READABLE_CHARS

    expected = max(len(cv_norm), 1)
    parse_ratio = min(char_count / expected, 1.0)
    grade = _grade(parse_ratio, pdf_readable)

    keywords = _job_keywords(job)
    found: list[str] = []
    missing: list[str] = []
    lost: list[str] = []
    for kw in keywords:
        kwn = _norm(kw)
        if kwn and kwn in pdf_norm:
            found.append(kw)
        else:
            missing.append(kw)
            if kwn and kwn in cv_norm:
                lost.append(kw)
    coverage = len(found) / len(keywords) if keywords else 1.0

    return SelfCheckReport(
        parse_ratio=parse_ratio,
        parse_grade=grade,
        pdf_readable=pdf_readable,
        char_count=char_count,
        keyword_coverage=coverage,
        keywords_checked=keywords,
        keywords_found_in_pdf=found,
        keywords_missing_in_pdf=missing,
        keywords_lost_in_render=lost,
    )
