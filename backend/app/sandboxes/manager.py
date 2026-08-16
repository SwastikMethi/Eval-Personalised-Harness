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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
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
def relay_script(dst_host: str = "host.docker.internal", dst_port: int = PROXY_PORT,
                 listen_port: int = PROXY_PORT, connect_timeout: int = 10) -> str:
    """The relay program, parameterised so a test can drive it without Docker."""
    return f"""
import socket, threading
DST = ("{dst_host}", {dst_port})
CONNECT_TIMEOUT = {connect_timeout}
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
        upstream = socket.create_connection(DST, CONNECT_TIMEOUT)
    except OSError:
        client.close()
        return
    # create_connection's timeout PERSISTS on the socket, so without this every
    # recv() inherits it: a model that thinks for longer than CONNECT_TIMEOUT
    # raised socket.timeout here, the pipe closed both ends, and the agent saw
    # "Server disconnected without sending a response" while the proxy happily
    # recorded a 200. Waiting for a slow model is the normal case, not an error.
    upstream.settimeout(None)
    client.settimeout(None)
    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
    threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", {listen_port}))
srv.listen(64)
while True:
    conn, _ = srv.accept()
    threading.Thread(target=handle, args=(conn,), daemon=True).start()
"""


@dataclass
class SandboxLimits:
    cpu: float = 2.0
    # From settings so it can be tuned without a code change, and so the
    # capacity guard and the container both read one number.
    memory_mb: int = field(default_factory=lambda: settings.sandbox_memory_mb)
    pids: int = 256
    timeout_s: int = 1800


class SandboxError(Exception):
    pass


def _died_message(container: Any, run_id: str, command: str, exc: Exception) -> str:
    """Explain a failed exec by asking the container why it is gone.

    Docker answers a exec-on-dead-container with a bare 409 Conflict quoting a
    64-char container id, which surfaced to the user verbatim and says nothing
    about the cause. The exit code does: 137 means the agent was killed for
    memory, which is a config problem, not a harness bug.

    The hint used to require `oom_killed` — and that is exactly the flag this
    kill does NOT set. `capacity.py` records why: a VM-level kernel kill leaves
    the cgroup flag false and emits no `oom` event. So the case that most needed
    the explanation was the one guaranteed not to get it, and a smolagents run
    died with `137 oom_killed=False` and no guidance at all. Keyed on the exit
    code now, and deliberately vague about WHICH limit, because without a
    recorded peak_memory we genuinely do not know.
    """
    state: dict[str, Any] = {}
    try:
        container.reload()
        state = container.attrs.get("State", {})
    except Exception:  # noqa: BLE001 - the container may be gone entirely
        pass
    if not state:
        return (
            f"sandbox container for {run_id} is gone and its state could not be read "
            f"(command: {command[:120]}). Underlying error: {exc}"
        )
    oom = state.get("OOMKilled")
    exit_code = state.get("ExitCode")
    detail = f"status={state.get('Status')} exit_code={exit_code} oom_killed={oom}"
    if oom:
        hint = " — the container exceeded its own memory limit; raise sandbox_memory_mb"
    elif exit_code == 137:
        hint = (
            " — killed for memory (SIGKILL). oom_killed=False does not rule this out: a"
            " VM-level kill leaves that flag false (see sandboxes/capacity.py). Check the"
            " run's peak_memory against sandbox_memory_mb, and the VM's total against the"
            " containers alive at the time"
        )
    else:
        hint = ""
    return (
        f"sandbox container for {run_id} exited before the command could run "
        f"({detail}){hint}. Command: {command[:120]}"
    )


def _docker() -> Any:
    import docker

    return docker.from_env()


def container_kwargs(
    workspace: Path,
    run_id: str,
    limits: "SandboxLimits | None" = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Creation flags shared by the agent sandbox and the evaluation sandbox.

    One definition on purpose: if evaluation containers were configured
    separately they would quietly drift from the agent's hardening, and the
    weaker of the two is the one that matters.
    """
    limits = limits or SandboxLimits()
    return {
        "command": "sleep infinity",
        "detach": True,
        "user": str(SANDBOX_UID),
        "working_dir": "/workspace",
        "volumes": {str(workspace): {"bind": "/workspace", "mode": "rw"}},
        "environment": {"HOME": "/tmp", **(env or {})},
        "labels": {RUN_LABEL: run_id},
        "nano_cpus": int(limits.cpu * 1e9),
        "mem_limit": f"{limits.memory_mb}m",
        "pids_limit": limits.pids,
        "security_opt": ["no-new-privileges"],
        "cap_drop": ["ALL"],
        "tmpfs": {"/tmp": "size=512m"},
        "extra_hosts": {"host.docker.internal": "host-gateway"},
        "network_mode": "bridge",
    }


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
        image: str | None = None,
    ) -> None:
        """`image` overrides the base — the queue passes a prepared image so the
        agent's PREP dependency install collapses to a no-op."""

        def _create() -> Any:
            client = _docker()
            return client.containers.run(
                image or self._image,
                **container_kwargs(workspace, run_id, limits, env),
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
                command=["python3", "-c", relay_script()],
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

        # An HTTP round-trip, not a bare TCP connect. The relay accepts the
        # client socket BEFORE it tries to reach the host, so connect() always
        # succeeded — including when the proxy was bound to loopback and the
        # relay could not reach it at all. Every run then failed deep inside
        # the harness with an opaque "Connection error" instead of failing
        # closed here, which is precisely what this check exists to prevent.
        # Retried, because the relay container is started detached moments
        # earlier and its listener may not be up yet. A single shot turned that
        # startup race into a failed run. Still fail-closed: exhausting every
        # attempt refuses to run.
        probe = (
            f"timeout 10 python3 -c \"import urllib.request;"
            f"urllib.request.urlopen('http://{relay_name}:{PROXY_PORT}/api/v1/health',timeout=8)"
            '.read()"'
        )
        reachable = await self.exec(
            run_id,
            f"for i in 1 2 3 4 5 6; do {probe} >/dev/null 2>&1 && "
            "{ echo PROXY_OK; break; }; sleep 2; done; echo DONE",
            timeout_s=90,
        )
        if "PROXY_OK" not in reachable.stdout:
            await self.cleanup(run_id)
            raise SandboxError(
                f"seal verification failed for {run_id}: model proxy unreachable via relay "
                "— the run would make zero model requests and look successful. "
                f"Is the backend bound to 0.0.0.0:{PROXY_PORT}? A server on 127.0.0.1 "
                "is not reachable from a container."
            )

    async def exec(
        self, run_id: str, command: str, timeout_s: int = 600, workdir: str = "/workspace"
    ) -> CommandResult:
        container = self._containers[run_id]
        start = time.monotonic()

        def _exec() -> tuple[int, bytes, bytes]:
            try:
                result = container.exec_run(
                    ["timeout", str(timeout_s), "sh", "-lc", command],
                    workdir=workdir,
                    demux=True,
                )
            except Exception as exc:  # noqa: BLE001 - re-raised with diagnosis below
                raise SandboxError(_died_message(container, run_id, command, exc)) from exc
            out, err = result.output or (b"", b"")
            return result.exit_code, out or b"", err or b""

        exit_code, out, err = await asyncio.to_thread(_exec)
        truncated = len(out) > MAX_OUTPUT_BYTES or len(err) > MAX_OUTPUT_BYTES
        return CommandResult(
            command=command,
            exit_code=exit_code,
            stdout=out[:MAX_OUTPUT_BYTES].decode(errors="replace"),
            # Demuxed, so stdout stays parseable. Merging the streams meant
            # every `cat result.json` could be corrupted by a stray warning,
            # and stderr — where smolagents writes its reasoning — was
            # hardcoded empty, leaving completed runs with no transcript.
            stderr=err[:MAX_OUTPUT_BYTES].decode(errors="replace"),
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
