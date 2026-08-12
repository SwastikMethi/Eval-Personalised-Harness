"""Docker-backed command executor for baseline and evaluation.

`exec.py` always described this: "HostExecutor runs on the host; the Docker
executor lands in Stage 4 behind the same shape." This is that executor.

Why it matters: running evaluator commands on the host means `pip` and the
test runner resolve to whatever happens to be on PATH. On a machine with both
miniforge and a uv-managed Python, install writes to one interpreter and the
tests run under another — install reports success while installing nothing the
tests can see. A container gives one interpreter by construction.

Synchronous on purpose. Both callers are already sync (`repos_analysis` is a
sync endpoint, `queue._evaluate` runs in `asyncio.to_thread`), and the Docker
SDK is synchronous underneath `SandboxManager`'s thread wrappers.
"""

import logging
import time
import uuid
from pathlib import Path
from types import TracebackType
from typing import Any

from app.sandboxes.exec import MAX_OUTPUT_BYTES, CommandResult
from app.sandboxes.manager import SandboxLimits, container_kwargs

log = logging.getLogger(__name__)


class ContainerExecutor:
    """One container for a whole baseline or evaluation.

    Used as a context manager; the returned object is callable with the same
    signature as `run_host_command`, so `run_baseline` and `evaluate` cannot
    tell the difference.
    """

    def __init__(
        self,
        workspace: Path,
        image: str,
        limits: SandboxLimits | None = None,
        label: str = "eval",
    ) -> None:
        self._workspace = workspace.resolve()
        self._image = image
        self._limits = limits or SandboxLimits()
        self._id = f"aso-{label}-{uuid.uuid4().hex[:12]}"
        self._container: Any = None

    def __enter__(self) -> "ContainerExecutor":
        import docker

        client = docker.from_env()
        self._container = client.containers.run(
            self._image,
            **container_kwargs(self._workspace, self._id, self._limits),
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._container is not None:
            try:
                self._container.remove(force=True)
            except Exception:  # noqa: BLE001 - already gone is fine
                log.warning("could not remove eval container", extra={"id": self._id})
            self._container = None

    def __call__(
        self,
        command: str,
        cwd: Path | None = None,
        timeout_s: int = 600,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        """`cwd` is translated into the container.

        The mounted root appears at /workspace, so a caller asking for a
        subdirectory (the evaluator grades in `workdir/graded`) must land in the
        matching path inside the container, not at the mount root.
        """
        assert self._container is not None, "use ContainerExecutor as a context manager"
        start = time.monotonic()
        prefix = " ".join(f"{k}={v}" for k, v in (env or {}).items())
        full = f"{prefix} {command}".strip() if prefix else command

        workdir = "/workspace"
        if cwd is not None:
            try:
                rel = cwd.resolve().relative_to(self._workspace)
                if str(rel) != ".":
                    workdir = f"/workspace/{rel}"
            except ValueError:
                # Outside the mount: fall back to the root rather than pointing
                # at a path that does not exist inside the container.
                log.warning("cwd %s is outside the mounted workspace", cwd)

        result = self._container.exec_run(
            ["timeout", str(timeout_s), "sh", "-lc", full],
            workdir=workdir,
            demux=False,
        )
        output = result.output or b""
        truncated = len(output) > MAX_OUTPUT_BYTES
        return CommandResult(
            command=command,
            exit_code=result.exit_code,
            stdout=output[:MAX_OUTPUT_BYTES].decode(errors="replace"),
            stderr="",
            duration_s=time.monotonic() - start,
            truncated=truncated,
            timed_out=result.exit_code == 124,  # GNU timeout convention
        )
