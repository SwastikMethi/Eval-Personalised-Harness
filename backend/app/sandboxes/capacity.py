"""How many runs the Docker VM can actually hold at once.

Parallelism cuts wall-clock time, but a concurrency the VM cannot hold does not
queue — it overcommits, and the VM's kernel kills containers. That is how a run
lost 28 successful model calls: two containers each permitted 4 GiB on a
7.65 GiB VM, killed with `exit 137, oom_killed=False` (a VM-level kill leaves the
cgroup flag false and emits no `oom` event, which is why it looked mysterious).

So concurrency is derived from measured capacity rather than hoped for. Raising
Docker Desktop's memory allocation raises parallelism on its own; shrinking it
lowers parallelism instead of producing dead runs.
"""

import logging

from app.core.config import settings

log = logging.getLogger(__name__)

# A relay container accompanies every sealed run (128m in seal()), so a run in
# flight costs its sandbox plus the relay.
RELAY_MB = 128


def docker_memory_mb() -> int | None:
    """The VM's total memory, or None when Docker cannot be asked."""
    try:
        import docker

        total = docker.from_env().info().get("MemTotal")
        return int(total) // (1024 * 1024) if total else None
    except Exception:  # noqa: BLE001 - no docker is not an error here
        return None


def max_parallel_runs(vm_memory_mb: int | None = None) -> int | None:
    """How many runs fit, or None when capacity cannot be determined."""
    total = vm_memory_mb if vm_memory_mb is not None else docker_memory_mb()
    if not total:
        return None
    usable = total * settings.sandbox_memory_headroom
    per_run = settings.sandbox_memory_mb + RELAY_MB
    # Never zero: one run at a time is always allowed, because refusing to run
    # anything is worse than running one thing slowly.
    return max(1, int(usable // per_run))


def effective_concurrency(configured: int, vm_memory_mb: int | None = None) -> int:
    """The configured concurrency, clamped to what the VM can hold.

    Unknown capacity returns the configured value unchanged: this guard exists to
    prevent overcommitment, not to refuse to work when Docker is unreachable
    (the fake harness needs no containers at all).
    """
    fits = max_parallel_runs(vm_memory_mb)
    if fits is None or configured <= fits:
        return configured
    log.warning(
        "clamping run concurrency to what the Docker VM can hold",
        extra={
            "event_type": "concurrency_clamped",
            "configured": configured,
            "allowed": fits,
        },
    )
    return fits
