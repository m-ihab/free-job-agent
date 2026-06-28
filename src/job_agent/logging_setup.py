"""Backward-compatible logging setup seam."""
from __future__ import annotations

from job_agent.logging_config import configure_logging, resolve_level

__all__ = ["configure_logging", "resolve_level"]
