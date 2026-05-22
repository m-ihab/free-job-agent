"""Shared cache helpers for API calls."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


DEFAULT_CACHE_TTL_HOURS = 6.0


def cache_dir() -> Path:
    return Path(os.environ.get("JOB_AGENT_API_CACHE_DIR") or (Path.home() / ".job_agent" / "api_cache"))


def cache_key(url: str, params: dict[str, Any] | None) -> str:
    payload = json.dumps({"url": url, "params": params or {}}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest() + ".json"


def read_cached_json(url: str, params: dict[str, Any] | None, ttl_hours: float) -> Any | None:
    if ttl_hours <= 0:
        return None
    path = cache_dir() / cache_key(url, params)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl_hours * 3600:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_cached_json(url: str, params: dict[str, Any] | None, payload: Any) -> None:
    try:
        cache_dir().mkdir(parents=True, exist_ok=True)
        path = cache_dir() / cache_key(url, params)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return
