"""CV Studio — local-AI edit suggestions for the current draft."""
from __future__ import annotations

from typing import Any

from job_agent.utils.html import strip_html

try:
    from job_agent.ai_agent import _call_ollama_json as _ai_call_json  # type: ignore[attr-defined]
    from job_agent.ai_agent import is_available as _ai_is_available
    from job_agent.polish import PolishOptions
except Exception:  # pragma: no cover - AI is optional
    _ai_call_json = None  # type: ignore[assignment]
    _ai_is_available = None  # type: ignore[assignment]
    PolishOptions = None  # type: ignore[assignment,misc]


_SUGGEST_PROMPT = """You review a LaTeX CV draft for a Paris data/AI candidate
applying to a specific job. Return JSON only:

{
  "suggestions": [
    {
      "title": "short label",
      "section": "summary|skills|experience|projects|education|other",
      "priority": "high|medium|low",
      "rationale": "one sentence",
      "before": "exact excerpt the user has now (<= 200 chars) or empty",
      "after": "rewrite proposal (<= 220 chars) or empty"
    }
  ]
}

Rules:
- Never invent dates, metrics, companies, sponsorship claims, or facts.
- 3-6 suggestions max. Skip if the CV is already great.
- "before" must be an exact substring of the source if non-empty.
- Tone: professional, concise, role-aware.

CV (truncated to 12000 chars):
{cv}

JOB CONTEXT (may be empty):
{job}

JSON:"""


def suggest_edits(
    cv_text: str,
    job_context: str = "",
    *,
    options: "PolishOptions | None" = None,
) -> dict[str, Any]:
    """Ask the local AI for concrete CV edit suggestions."""
    if _ai_is_available is None or _ai_call_json is None or PolishOptions is None:
        return {"available": False, "suggestions": []}
    opts = options or PolishOptions.from_env()
    if not _ai_is_available(opts):
        return {"available": False, "suggestions": []}
    prompt = (
        _SUGGEST_PROMPT
        .replace("{cv}", strip_html(cv_text or "")[:12000])
        .replace("{job}", strip_html(job_context or "")[:1500])
    )
    raw = _ai_call_json(prompt, opts)
    if not isinstance(raw, dict):
        return {"available": True, "suggestions": []}
    suggestions: list[dict[str, Any]] = []
    for item in (raw.get("suggestions") or [])[:8]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:80]
        if not title:
            continue
        suggestions.append({
            "title": title,
            "section": str(item.get("section") or "other").strip().lower(),
            "priority": str(item.get("priority") or "medium").strip().lower(),
            "rationale": str(item.get("rationale") or "").strip()[:240],
            "before": str(item.get("before") or "").strip()[:600],
            "after": str(item.get("after") or "").strip()[:600],
        })
    return {"available": True, "suggestions": suggestions}
