"""Date/time helpers."""
from __future__ import annotations

import datetime as _dt


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
