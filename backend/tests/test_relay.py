"""The sandbox relay must survive a slow model.

Agents on a sealed network reach the model proxy only through the relay, so
anything the relay drops is indistinguishable to the harness from the model
failing. It used to drop every request that took longer than its connect
timeout: socket.create_connection(DST, 10) leaves that 10s timeout ON the
socket, so the pipe's recv() raised socket.timeout while waiting for the
model, closed both ends, and the agent got "Server disconnected without
sending a response" — while the proxy recorded a perfectly good 200.

That made every model slower than 10 seconds look like a broken harness, and
it is why a real matrix run produced no patches: one model answered in ~3s and
sometimes worked, the other took 20-600s and never did.

The relay program runs here as a plain subprocess against a local slow server,
so this costs no Docker and no quota.
"""

import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator

import pytest

from app.sandboxes.manager import relay_script

DELAY_S = 2.0
CONNECT_TIMEOUT_S = 1  # deliberately shorter than DELAY_S


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def slow_server() -> Iterator[int]:
    """Accepts, waits longer than the relay's connect timeout, then answers."""
    port = _free_port()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(8)
    stop = threading.Event()

    def serve() -> None:
        srv.settimeout(0.5)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except (TimeoutError, OSError):
                continue
            conn.recv(65536)
            time.sleep(DELAY_S)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield port
    stop.set()
    thread.join(timeout=3)
    srv.close()


def test_relay_waits_for_a_slow_response(slow_server: int) -> None:
    listen_port = _free_port()
    script = relay_script(
        dst_host="127.0.0.1",
        dst_port=slow_server,
        listen_port=listen_port,
        connect_timeout=CONNECT_TIMEOUT_S,
    )
    relay = subprocess.Popen([sys.executable, "-c", script])
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                client = socket.create_connection(("127.0.0.1", listen_port), 1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("relay never started listening")

        with client:
            client.settimeout(10)
            client.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            body = client.recv(65536)

        # Before the fix this was b"" — the relay closed the connection at
        # CONNECT_TIMEOUT_S and the caller saw a disconnect, not a response.
        assert body.startswith(b"HTTP/1.1 200 OK"), (
            f"relay dropped a response that took {DELAY_S}s: {body!r}"
        )
    finally:
        relay.terminate()
        relay.wait(timeout=5)
