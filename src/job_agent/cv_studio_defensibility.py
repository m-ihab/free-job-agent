"""CV Studio claim defensibility checks.

The Studio editor is allowed to be creative, but the final CV should only make
claims that can be backed by the user's local profile/CV/QA evidence. This
module turns a LaTeX draft into candidate-facing claim lines and asks the
EvidenceStore whether each line is supported.
"""
from __future__ import annotations

import re
from typing import Any

from job_agent.config import AppConfig
from job_agent.cv_studio_core import _active_cv_text
from job_agent.evidence import EvidenceItem, EvidenceStore


_MIN_CLAIM_TOKENS = 3
_MAX_EVIDENCE_ITEMS = 3
_IGNORE_COMMAND_PREFIXES = (
    r"\documentclass",
    r"\usepackage",
    r"\geometry",
    r"\moderncv",
    r"\definecolor",
    r"\colorlet",
    r"\pagestyle",
    r"\begin",
    r"\end",
    r"\clearpage",
    r"\vspace",
    r"\hspace",
)
_CONTACT_HINTS = ("mailto:", "linkedin.com", "github.com", "tel:", "@")


def defensibility_report(config: AppConfig, text: str | None = None) -> dict[str, Any]:
    """Return evidence support for claim-like lines in the current CV draft."""
    if text is None:
        text, _path, origin = _active_cv_text(config)
    else:
        origin = "payload"

    evidence = EvidenceStore.load(config)
    if not evidence.all():
        evidence.rebuild(config)

    claim_lines = list(_extract_claim_lines(text or ""))
    backed_lines: list[dict[str, Any]] = []
    unbacked_lines: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []

    for line in claim_lines:
        match = evidence.supports(line["text"])
        row = {
            "line": line["line"],
            "text": line["text"],
            "confidence": match.confidence,
            "numbers": _numbers(line["text"]),
        }
        if match.matched:
            row["evidence"] = [_evidence_to_dict(item) for item in match.items[:_MAX_EVIDENCE_ITEMS]]
            backed_lines.append(row)
            continue
        row["reason"] = _reason_for_unbacked(line["text"], row["numbers"])
        unbacked_lines.append(row)

    checked = len(claim_lines)
    backed = len(backed_lines)
    unbacked = len(unbacked_lines)
    if checked == 0:
        score = 100
        warnings.append({"level": "info", "text": "No claim-like CV lines were detected."})
    else:
        numeric_penalty = sum(1 for row in unbacked_lines if row["numbers"])
        score = max(0, round((backed / checked) * 100) - numeric_penalty * 8)

    return {
        "ok": True,
        "origin": origin,
        "score": score,
        "checked": checked,
        "backed": backed,
        "unbacked": unbacked,
        "backed_lines": backed_lines,
        "unbacked_lines": unbacked_lines,
        "warnings": warnings,
    }


def _extract_claim_lines(text: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for index, raw in enumerate(text.splitlines(), start=1):
        cleaned = _latex_line_to_text(raw)
        if not _is_claim_like(cleaned, raw):
            continue
        claims.append({"line": index, "text": cleaned})
    return claims


def _latex_line_to_text(raw: str) -> str:
    line = re.sub(r"(?<!\\)%.*$", "", raw).strip()
    if not line:
        return ""
    if line.lstrip().startswith(_IGNORE_COMMAND_PREFIXES):
        return ""
    # Remove common macro names while preserving their argument text.
    line = re.sub(r"\\newcommand\s*\{\\[A-Za-z@]+\}", " ", line)
    line = re.sub(r"\\[A-Za-z@*]+(?:\[[^\]]*\])?", " ", line)
    line = line.replace(r"\&", "&").replace(r"\%", "%").replace(r"\_", "_")
    line = re.sub(r"[{}[\]$]", " ", line)
    line = re.sub(r"\s+", " ", line).strip(" ;,.")
    return line


def _is_claim_like(cleaned: str, raw: str) -> bool:
    if not cleaned:
        return False
    lower = cleaned.casefold()
    if any(hint in lower for hint in _CONTACT_HINTS):
        return False
    if raw.lstrip().startswith(r"\section"):
        return False
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{2,}", cleaned)
    if len(tokens) < _MIN_CLAIM_TOKENS:
        return False
    # Skill lists, project bullets and summary macros are all claim-like. Very
    # short labels such as "Education" should have been filtered by token count.
    return True


def _reason_for_unbacked(text: str, numbers: list[str]) -> str:
    if numbers:
        return "Numeric claim is not present in the local evidence store."
    if len(text) > 150:
        return "Long claim has weak evidence overlap; split it or cite a clearer project."
    return "No strong local evidence match found."


def _numbers(value: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?%?", value.casefold())


def _evidence_to_dict(item: EvidenceItem) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "label": item.label,
        "value": item.value,
        "source": item.source,
        "source_ref": item.source_ref,
        "confidence": item.confidence,
    }

