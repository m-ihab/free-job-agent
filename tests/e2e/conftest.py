"""pytest-playwright configuration for E2E tests.

Registers the live_server_url fixture at the conftest level so it is
available to all test modules under tests/e2e/.
"""
from __future__ import annotations

import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Generator

import pytest

from job_agent.config import AppConfig
from job_agent.db.database import Database
from job_agent.ui.server import JobAgentHandler, JobAgentServer


EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def e2e_config(tmp_path_factory: pytest.TempPathFactory) -> AppConfig:
    root = tmp_path_factory.mktemp("e2e_data")
    profiles_dir = root / "profiles"
    profiles_dir.mkdir()
    for name in ("candidate_profile.json", "master_cv.json", "master_qa_profile.json"):
        src = EXAMPLES_DIR / name
        if src.exists():
            shutil.copy(src, profiles_dir / name)
    config = AppConfig(data_dir=root, profiles_dir=profiles_dir)
    config.ensure_dirs()
    Database(config.db_path).initialize()  # type: ignore[arg-type]
    return config


@pytest.fixture(scope="session")
def live_server_url(e2e_config: AppConfig) -> Generator[str, None, None]:
    port = _free_port()
    server = JobAgentServer(("127.0.0.1", port), JobAgentHandler, e2e_config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.15)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=3)
