"""Global recovery test policies."""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def _block_external_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Fail fast if a default unit test attempts a real network connection."""
    if request.node.get_closest_marker("integration"):
        yield
        return

    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked_connect(sock, address):
        host = address[0] if isinstance(address, tuple) and address else str(address)
        if host in {"127.0.0.1", "::1", "localhost"}:
            return original_connect(sock, address)
        raise RuntimeError(f"External network is disabled in default tests: {host}")

    def blocked_create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) and address else str(address)
        if host in {"127.0.0.1", "::1", "localhost"}:
            return original_create_connection(address, *args, **kwargs)
        raise RuntimeError(f"External network is disabled in default tests: {host}")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    monkeypatch.setattr(socket, "create_connection", blocked_create_connection)
    yield
