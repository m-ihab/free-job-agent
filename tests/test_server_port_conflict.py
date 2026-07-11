"""run_server must fail loudly and clearly when the port is already taken.

2026-07-11 incident: a stale dashboard instance kept the port for two days;
new launches died with a raw traceback in a closing console window, and the
browser silently connected to the stale instance (which served a different
database), so every tracked job looked deleted.
"""
from __future__ import annotations

import logging
import socket

import pytest

from job_agent.ui import server as ui_server


def test_run_server_exits_with_clear_message_when_port_taken(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("JOB_AGENT_DATA_DIR", str(tmp_path / "data"))
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    try:
        with caplog.at_level(logging.ERROR, logger="job_agent.ui.server"):
            with pytest.raises(SystemExit) as excinfo:
                ui_server.run_server(host="127.0.0.1", port=port, open_browser=False)
        assert excinfo.value.code == 2
        assert any("another dashboard instance" in rec.getMessage().lower() for rec in caplog.records), caplog.text
    finally:
        blocker.close()
