"""Central logging configuration.

Most of the codebase historically swallowed exceptions silently, leaving no
diagnostic trail. This wires a single stderr handler whose level is controlled
by ``JOB_AGENT_LOG_LEVEL`` (default ``WARNING``) so failures are visible without
being noisy. Call :func:`configure_logging` once at each entry point (CLI / UI).
"""
from __future__ import annotations

import logging
import os

_LEVEL_ENV = "JOB_AGENT_LOG_LEVEL"
_DEFAULT_LEVEL = "WARNING"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False


def resolve_level(raw: str | None = None) -> int:
    name = (raw if raw is not None else os.environ.get(_LEVEL_ENV, _DEFAULT_LEVEL)).strip().upper()
    return getattr(logging, name, logging.WARNING)


def configure_logging(*, force: bool = False) -> None:
    """Idempotently configure the root logger from the environment."""
    global _configured
    if _configured and not force:
        return
    logging.basicConfig(level=resolve_level(), format=_FORMAT)
    _configured = True
