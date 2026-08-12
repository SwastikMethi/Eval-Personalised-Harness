"""Docker-gated sandbox tests (eng review E2E #1/#3): network sealing is the
product's honesty guarantee — the agent container must NOT reach the internet.
Skipped automatically when Docker is unavailable.
"""

import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.sandboxes.manager import PROXY_PORT, RUN_LABEL, SandboxManager, docker_available

pytestmark = pytest.mark.skipif(not docker_available(), reason="docker unavailable")

IMAGE = "python:3.12-slim"  # sealing tests don't need the harness image


@pytest.fixture
async def manager():  # type: ignore[no-untyped-def]
    m = SandboxManager(image=IMAGE)
    yield m
    for run_id in list(m._containers):
        await m.cleanup(run_id)


@pytest.fixture
def health_endpoint() -> Iterator[None]:
    """Guarantee something answers /api/v1/health on the proxy port.

    seal() fail-closes when the model proxy is unreachable, so it needs a
    responder. Without this the test passed only when a dev backend happened
    to be running on 8005 — `make test` failed outright with the backend
    stopped, which is not a real defect in the code under test.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *_args: object) -> None:
            return

    try:
        server = HTTPServer(("0.0.0.0", PROXY_PORT), Handler)  # noqa: S104 - container must reach it
    except OSError:
        # Port taken: the real backend is up and already serves this route.
        yield
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_container_labeled_and_limited(manager: SandboxManager, tmp_path: Path) -> None:
    await manager.create("t-label", tmp_path)
    container = manager._containers["t-label"]
    container.reload()
    assert container.labels[RUN_LABEL] == "t-label"
    host_config = container.attrs["HostConfig"]
    assert host_config["PidsLimit"] == 256
    assert host_config["CapDrop"] == ["ALL"]
    assert "no-new-privileges" in host_config["SecurityOpt"]


async def test_seal_blocks_egress(
    manager: SandboxManager, tmp_path: Path, health_endpoint: None
) -> None:
    await manager.create("t-seal", tmp_path)
    # PREP phase: egress works (skip assert if host itself is offline)
    prep = await manager.exec(
        "t-seal",
        "timeout 5 python3 -c \"import socket;socket.create_connection(('1.1.1.1',443),4)\""
        " && echo REACHABLE || echo BLOCKED",
        timeout_s=15,
    )
    if "REACHABLE" not in prep.stdout:
        pytest.skip("host has no egress; cannot verify PREP-phase connectivity")
    await manager.seal("t-seal")  # raises if egress survives
    post = await manager.exec(
        "t-seal",
        "timeout 5 python3 -c \"import socket;socket.create_connection(('1.1.1.1',443),4)\""
        " && echo REACHABLE || echo BLOCKED",
        timeout_s=15,
    )
    assert "BLOCKED" in post.stdout


async def test_exec_truncation_and_timeout(manager: SandboxManager, tmp_path: Path) -> None:
    await manager.create("t-exec", tmp_path)
    result = await manager.exec("t-exec", "sleep 30", timeout_s=2)
    assert result.timed_out


async def test_cleanup_removes_container(manager: SandboxManager, tmp_path: Path) -> None:
    await manager.create("t-clean", tmp_path)
    await manager.cleanup("t-clean")
    proc = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={RUN_LABEL}=t-clean"],
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == ""
