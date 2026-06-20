"""Local AgentCore-style routing and observability.

The project runs mostly on local Ollama, so this is about latency and machine
load rather than cloud spend. It still follows the same idea: use the smallest
capable "brain" for each task and keep lightweight traces for debugging.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from job_agent.polish import PolishOptions, resolve_fast_model, resolve_ollama_model

Tier = Literal["L1", "L2", "L3"]


@dataclass(frozen=True)
class AgentRoute:
    task: str
    tier: Tier
    model: str
    reason: str
    estimated_input_tokens: int
    max_output_tokens: int

    def to_dict(self) -> dict:
        return asdict(self)


_FAST_TASKS = {
    "chat": 512,
    "classify": 512,
    "summarize": 384,
    "search_plan": 384,
}
_HEAVY_TASKS = {
    "fit_analysis": 768,
    "tailored_summary": 512,
    "cover_letter_bullets": 512,
    "cover_letter_body": 1024,
    "cv_suggestions": 1024,
}


def estimate_tokens(text: str) -> int:
    """Cheap token estimate good enough for routing and traces."""
    text = text or ""
    return max(1, int(len(text) / 4))


def choose_route(task: str, prompt: str, options: PolishOptions | None = None) -> AgentRoute:
    """Choose the model tier for a local AI task."""
    options = options or PolishOptions.from_env()
    task = (task or "general").strip().lower()
    token_estimate = estimate_tokens(prompt)

    if task in _FAST_TASKS and token_estimate < 3_500:
        return AgentRoute(
            task=task,
            tier="L1",
            model=resolve_fast_model(options),
            reason="fast structured/local chat task",
            estimated_input_tokens=token_estimate,
            max_output_tokens=_FAST_TASKS[task],
        )
    if task in _HEAVY_TASKS or token_estimate > 6_000:
        return AgentRoute(
            task=task,
            tier="L3",
            model=resolve_ollama_model(options),
            reason="strategic tailoring or long context",
            estimated_input_tokens=token_estimate,
            max_output_tokens=_HEAVY_TASKS.get(task, 1024),
        )
    return AgentRoute(
        task=task,
        tier="L2",
        model=resolve_fast_model(options),
        reason="operational worker task",
        estimated_input_tokens=token_estimate,
        max_output_tokens=512,
    )


def trace_path() -> Path:
    base = Path(os.environ.get("JOB_AGENT_DATA_DIR") or ".job_agent").expanduser()
    return base / "ai_traces.jsonl"


def record_trace(route: AgentRoute, *, ok: bool, elapsed_ms: int, error: str = "") -> None:
    """Append a prompt-free trace line. Fail silently; traces are diagnostic."""
    try:
        path = trace_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ok": bool(ok),
            "elapsed_ms": int(elapsed_ms),
            "error": (error or "")[:240],
            **route.to_dict(),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


def read_traces(limit: int = 50) -> list[dict]:
    """Return the most recent AI traces (newest first). Prompt-free + safe."""
    path = trace_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except (ValueError, TypeError):
            continue
        if len(out) >= max(1, limit):
            break
    return out


def trace_summary(limit: int = 200) -> dict:
    """Aggregate recent traces for the AI trace panel: per-tier counts,
    average latency, and success rate. Powers the UI without exposing prompts.
    """
    traces = read_traces(limit)
    by_tier: dict[str, dict[str, float]] = {}
    ok_count = 0
    for t in traces:
        tier = str(t.get("tier") or "?")
        bucket = by_tier.setdefault(tier, {"count": 0, "ok": 0, "total_ms": 0})
        bucket["count"] += 1
        bucket["total_ms"] += int(t.get("elapsed_ms") or 0)
        if t.get("ok"):
            bucket["ok"] += 1
            ok_count += 1
    tiers = {
        tier: {
            "count": int(b["count"]),
            "success_rate": round(b["ok"] / b["count"], 3) if b["count"] else 0.0,
            "avg_ms": int(b["total_ms"] / b["count"]) if b["count"] else 0,
        }
        for tier, b in sorted(by_tier.items())
    }
    total = len(traces)
    return {
        "total": total,
        "success_rate": round(ok_count / total, 3) if total else 0.0,
        "tiers": tiers,
        "recent": traces[:20],
    }
