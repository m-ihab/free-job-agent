"""Fast recruiter-style scan for CV Studio drafts."""
from __future__ import annotations

import re
from dataclasses import dataclass

from job_agent.cv_studio_core import is_valid_latex_cv


@dataclass(frozen=True)
class ScanIssue:
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


def six_second_scan(text: str) -> dict[str, object]:
    """Return quick readability signals for a LaTeX CV draft.

    This is intentionally heuristic. It flags things a recruiter notices first:
    missing contact/project sections, excessive placeholders, too much text, or
    a draft that is not a real LaTeX document.
    """
    issues: list[ScanIssue] = []
    if not is_valid_latex_cv(text):
        issues.append(ScanIssue("high", "Draft is not a complete LaTeX CV document."))
        return {"ok": False, "score": 0, "issues": [issue.to_dict() for issue in issues]}

    plain = _latex_to_plain(text)
    word_count = len(re.findall(r"\b\w+\b", plain))
    section_count = len(re.findall(r"\\section\*?\{", text))
    placeholder_count = len(re.findall(r"\[[A-Z][A-Za-z0-9 _/-]*\]", text))
    for pattern, label in (
        (r"linkedin\.com", "LinkedIn URL"),
        (r"github\.com", "GitHub URL"),
        (r"\\section\*?\{Projects?\}", "Projects section"),
        (r"\\section\*?\{Skills?\}", "Skills section"),
    ):
        if not re.search(pattern, text, flags=re.IGNORECASE):
            issues.append(ScanIssue("medium", f"Missing visible {label}."))
    if placeholder_count:
        issues.append(ScanIssue("high", f"{placeholder_count} unresolved placeholder(s) remain."))
    if word_count > 850:
        issues.append(ScanIssue("medium", "Draft may be too dense for a one-page CV."))
    if section_count < 4:
        issues.append(ScanIssue("low", "Few sections detected; check that the structure is intentional."))
    score = max(0, 100 - sum(25 if i.severity == "high" else 12 if i.severity == "medium" else 6 for i in issues))
    return {
        "ok": True,
        "score": score,
        "word_count": word_count,
        "section_count": section_count,
        "placeholder_count": placeholder_count,
        "issues": [issue.to_dict() for issue in issues],
    }


def _latex_to_plain(text: str) -> str:
    no_comments = re.sub(r"(?<!\\)%.*", " ", text)
    no_commands = re.sub(r"\\[A-Za-z@*]+(?:\[[^\]]*\])?", " ", no_comments)
    return re.sub(r"[{}$\\]+", " ", no_commands)


__all__ = ["ScanIssue", "six_second_scan"]
