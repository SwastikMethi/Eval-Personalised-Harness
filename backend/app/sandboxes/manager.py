"""Docker sandbox manager (spec §12, eng review 1A + Tension 1 + 3A).

Two-phase network lifecycle:

  PREP  — container on the default bridge: dependency install + baseline
          commands may reach the internet (agent is not running yet).
  AGENT — bridge disconnected; container joined to a per-run `internal: true`
          network. Internal networks have no default route, so general egress
          is dead. The model proxy stays reachable because the container was
          created with an extra_hosts host-gateway mapping and the proxy URL
          uses host.docker.internal — reaching the HOST gateway does not
          require a routable external network on Docker Desktop (macOS), which
          resolves host.docker.internal via the embedded VM gateway.
          seal() fail-closes: it probes external egress and refuses to report
          sealed if the probe succeeds.

All docker SDK calls run in threads (asyncio.to_thread) — the SDK is
synchronous and must never block the event loop (eng review Tension 5).
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.sandboxes.exec import MAX_OUTPUT_BYTES, CommandResult

log = logging.getLogger(__name__)

RUN_LABEL = "aso.run_id"
SANDBOX_UID = 1000
PROXY_PORT = 8005

# A container on an `internal: true` network has no default route AT ALL —
# not to the internet and not to the host gateway either, so
# host.docker.internal dies along with egress. Measured, not assumed: the
# proxy answered 200 before seal() and was unreachable after.
#
# So the agent talks to a relay that straddles both networks: it is attached
# to the run's internal network (where the agent can see it) and to the
# default bridge (where it can reach the host). The agent still has exactly
# one reachable destination and no route to the internet.
RELAY_SCRIPT = f"""
import socket, threading
DST = ("host.docker.internal", {PROXY_PORT})
def pipe(a, b):
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()
def handle(client):
    try:
        upstream = socket.create_connection(DST, 10)
    except OSError:
        client.close()
        return
    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
    threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", {PROXY_PORT}))
srv.listen(64)
while True:
    conn, _ = srv.accept()
    threading.Thread(target=handle, args=(conn,), daemon=True).start()
"""


@dataclass
class SandboxLimits:
    cpu: float = 2.0
    memory_mb: int = 4096
    pids: int = 256
    timeout_s: int = 1800


class SandboxError(Exception):
    pass


def _docker() -> Any:
    import docker

    return docker.from_env()


class SandboxManager:
    def __init__(self, image: str = "aso-sandbox-python:dev") -> None:
        self._image = image
        self._containers: dict[str, Any] = {}
        self._networks: dict[str, Any] = {}
        self._relays: dict[str, Any] = {}

    async def create(
        self,
        run_id: str,
        workspace: Path,
        limits: SandboxLimits | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        limits = limits or SandboxLimits()

        def _create() -> Any:
            client = _docker()
            return client.containers.run(
                self._image,
                command="sleep infinity",
                detach=True,
                user=str(SANDBOX_UID),
                working_dir="/workspace",
                volumes={str(workspace): {"bind": "/workspace", "mode": "rw"}},
                environment={"HOME": "/tmp", **(env or {})},
                labels={RUN_LABEL: run_id},
                nano_cpus=int(limits.cpu * 1e9),
                mem_limit=f"{limits.memory_mb}m",
                pids_limit=limits.pids,
                security_opt=["no-new-privileges"],
                cap_drop=["ALL"],
                tmpfs={"/tmp": "size=512m"},
                extra_hosts={"host.docker.internal": "host-gateway"},
                network_mode="bridge",
            )

        self._containers[run_id] = await asyncio.to_thread(_create)

    def relay_host(self, run_id: str) -> str:
        """Hostname the sealed agent uses to reach the model proxy."""
        return f"aso-relay-{run_id[:12]}"

    async def seal(self, run_id: str) -> None:
        """Switch PREP -> AGENT network.

        Fail-closed both ways: external egress must be dead, AND the model
        proxy must be reachable. Verifying only the first is how a sealed run
        silently made zero model requests and still reported success.
        """
        container = self._containers[run_id]
        relay_name = self.relay_host(run_id)

        def _seal() -> Any:
            client = _docker()
            network = client.networks.create(
                f"aso-internal-{run_id[:12]}", driver="bridge", internal=True,
                labels={RUN_LABEL: run_id},
            )
            # Relay first, so it is listening before the agent loses the bridge.
            relay = client.containers.run(
                self._image,
                command=["python3", "-c", RELAY_SCRIPT],
                detach=True,
                name=relay_name,
                labels={RUN_LABEL: run_id},
                extra_hosts={"host.docker.internal": "host-gateway"},
                network="bridge",
                mem_limit="128m",
                pids_limit=64,
                security_opt=["no-new-privileges"],
                cap_drop=["ALL"],
            )
            network.connect(relay, aliases=[relay_name])
            bridge = client.networks.get("bridge")
            bridge.disconnect(container)
            network.connect(container)
            self._networks[run_id] = network
            return relay

        self._relays[run_id] = await asyncio.to_thread(_seal)

        egress = await self.exec(
            run_id,
            "timeout 5 python3 -c \"import socket;socket.create_connection(('1.1.1.1',443),4)\""
            " && echo REACHABLE || echo BLOCKED",
            timeout_s=15,
        )
        if "BLOCKED" not in egress.stdout:
            await self.cleanup(run_id)
            raise SandboxError(f"seal verification failed for {run_id}: egress still open")

        reachable = await self.exec(
            run_id,
            f"timeout 20 python3 -c \"import socket;"
            f"socket.create_connection(('{relay_name}',{PROXY_PORT}),15)\""
            " && echo PROXY_OK || echo PROXY_DEAD",
            timeout_s=30,
        )
        if "PROXY_OK" not in reachable.stdout:
            await self.cleanup(run_id)
            raise SandboxError(
                f"seal verification failed for {run_id}: model proxy unreachable via relay "
                "— the run would make zero model requests and look successful"
            )

    async def exec(
        self, run_id: str, command: str, timeout_s: int = 600, workdir: str = "/workspace"
    ) -> CommandResult:
        container = self._containers[run_id]
        start = time.monotonic()

        def _exec() -> tuple[int, bytes]:
            result = container.exec_run(
                ["timeout", str(timeout_s), "sh", "-lc", command],
                workdir=workdir,
                demux=False,
            )
            return result.exit_code, result.output or b""

        exit_code, output = await asyncio.to_thread(_exec)
        truncated = len(output) > MAX_OUTPUT_BYTES
        return CommandResult(
            command=command,
            exit_code=exit_code,
            stdout=output[:MAX_OUTPUT_BYTES].decode(errors="replace"),
            stderr="",
            duration_s=time.monotonic() - start,
            truncated=truncated,
            timed_out=exit_code == 124,  # GNU timeout convention
        )

    async def stats(self, run_id: str) -> dict[str, Any]:
        container = self._containers.get(run_id)
        if container is None:
            return {}

        def _stats() -> dict[str, Any]:
            raw = container.stats(stream=False)
            return {
                "cpu_total_usage": raw.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage"),
                "peak_memory": raw.get("memory_stats", {}).get("max_usage"),
            }

        return await asyncio.to_thread(_stats)

    async def kill(self, run_id: str) -> None:
        container = self._containers.get(run_id)
        if container is None:
            return

        def _kill() -> None:
            try:
                container.kill()
            except Exception:  # noqa: BLE001 - already dead is fine
                pass

        await asyncio.to_thread(_kill)

    async def cleanup(self, run_id: str) -> None:
        container = self._containers.pop(run_id, None)
        network = self._networks.pop(run_id, None)
        relay = self._relays.pop(run_id, None)

        def _cleanup() -> None:
            # Containers before the network: a network with endpoints refuses
            # to be removed and would leak on every run.
            for target in (container, relay):
                if target is not None:
                    try:
                        target.remove(force=True)
                    except Exception:  # noqa: BLE001 - already gone is fine
                        pass
            if network is not None:
                try:
                    network.remove()
                except Exception:  # noqa: BLE001
                    pass

        await asyncio.to_thread(_cleanup)


def docker_available() -> bool:
    try:
        _docker().ping()
        return True
    except Exception:  # noqa: BLE001
        return False
