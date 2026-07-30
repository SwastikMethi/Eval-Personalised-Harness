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

    async def seal(self, run_id: str) -> None:
        """Switch PREP -> AGENT network. Fail-closed: verify egress is dead."""
        container = self._containers[run_id]

        def _seal() -> None:
            client = _docker()
            network = client.networks.create(
                f"aso-internal-{run_id[:12]}", driver="bridge", internal=True,
                labels={RUN_LABEL: run_id},
            )
            bridge = client.networks.get("bridge")
            bridge.disconnect(container)
            network.connect(container)
            self._networks[run_id] = network

        await asyncio.to_thread(_seal)
        probe = await self.exec(
            run_id,
            "timeout 5 python3 -c \"import socket;socket.create_connection(('1.1.1.1',443),4)\""
            " && echo REACHABLE || echo BLOCKED",
            timeout_s=15,
        )
        if "BLOCKED" not in probe.stdout:
            await self.cleanup(run_id)
            raise SandboxError(f"seal verification failed for {run_id}: egress still open")

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

        def _cleanup() -> None:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:  # noqa: BLE001
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
