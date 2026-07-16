from __future__ import annotations

from scripts import launch_web


class _FakeSocket:
    def __init__(self, bind_error: OSError | None = None) -> None:
        self.bind_error = bind_error
        self.address: tuple[str, int] | None = None
        self.closed = False

    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def bind(self, address: tuple[str, int]) -> None:
        self.address = address
        if self.bind_error is not None:
            raise self.bind_error


def test_dashboard_url_uses_host_and_port() -> None:
    assert launch_web.dashboard_url("127.0.0.1", 8765) == "http://127.0.0.1:8765"


def test_port_is_available_without_network(monkeypatch: object) -> None:
    fake_socket = _FakeSocket()
    monkeypatch.setattr(launch_web.socket, "socket", lambda *_args: fake_socket)  # type: ignore[attr-defined]

    assert launch_web.port_is_available("127.0.0.1", 8765) is True
    assert fake_socket.address == ("127.0.0.1", 8765)
    assert fake_socket.closed is True


def test_port_is_unavailable_when_bind_fails(monkeypatch: object) -> None:
    fake_socket = _FakeSocket(OSError("address already in use"))
    monkeypatch.setattr(launch_web.socket, "socket", lambda *_args: fake_socket)  # type: ignore[attr-defined]

    assert launch_web.port_is_available("127.0.0.1", 8765) is False
    assert fake_socket.closed is True
