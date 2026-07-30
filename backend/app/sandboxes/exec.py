"""Shared command execution layer (eng review 4A).

Baseline validation (Stage 2) and evaluators (Stage 5) both run repo commands
through this one interface so results are comparable. HostExecutor runs on
the host; the Docker executor lands in Stage 4 behind the same shape.
"""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_BYTES = 1_000_000


@dataclass
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    truncated: bool = False
    timed_out: bool = False


def _truncate(data: bytes) -> tuple[str, bool]:
    truncated = len(data) > MAX_OUTPUT_BYTES
    return data[:MAX_OUTPUT_BYTES].decode(errors="replace"), truncated


def run_host_command(
    command: str,
    cwd: Path,
    timeout_s: int = 600,
    env: dict[str, str] | None = None,
) -> CommandResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            timeout=timeout_s,
            env=env,
        )
        stdout, t1 = _truncate(proc.stdout)
        stderr, t2 = _truncate(proc.stderr)
        return CommandResult(
            command=command,
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_s=time.monotonic() - start,
            truncated=t1 or t2,
        )
    except subprocess.TimeoutExpired as exc:
        stdout, _ = _truncate(exc.stdout or b"")
        stderr, _ = _truncate(exc.stderr or b"")
        return CommandResult(
            command=command,
            exit_code=-1,
            stdout=stdout,
            stderr=stderr,
            duration_s=time.monotonic() - start,
            timed_out=True,
        )
