"""Start the local dashboard and open it in the default browser."""
from __future__ import annotations

import logging
import socket
import threading
import webbrowser

HOST = "127.0.0.1"
PORT = 8765

logger = logging.getLogger(__name__)


def dashboard_url(host: str, port: int) -> str:
    """Return the dashboard URL for a host and port."""
    return f"http://{host}:{port}"


def port_is_available(host: str, port: int) -> bool:
    """Return whether a TCP address can be bound locally."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, port))
    except OSError:
        return False
    return True


def main() -> int:
    """Launch the dashboard server and arrange to open its URL."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    url = dashboard_url(HOST, PORT)
    if not port_is_available(HOST, PORT):
        logger.error(
            "Cannot start the dashboard: %s is already in use. "
            "Close the existing process and try again.",
            url,
        )
        return 1

    from job_agent.ui.server import run_server

    browser_timer = threading.Timer(0.75, webbrowser.open, args=(url,))
    browser_timer.daemon = True
    browser_timer.start()
    logger.info("Starting dashboard at %s", url)
    run_server(host=HOST, port=PORT, open_browser=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
