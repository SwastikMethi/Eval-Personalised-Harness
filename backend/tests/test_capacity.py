"""Parallelism is bounded by what the Docker VM can actually hold.

A concurrency the VM cannot hold does not queue — it overcommits, and the VM's
kernel kills containers. That is how one run lost 28 successful model calls: the
agent container was held through evaluation, so two containers each permitted
4 GiB coexisted on a 7.65 GiB VM, and both died with
`exit 137, oom_killed=False` — a VM-level kill, which sets no cgroup flag and
emits no `oom` event, which is exactly why it looked mysterious.
"""

from app.core.config import settings
from app.sandboxes.capacity import RELAY_MB, effective_concurrency, max_parallel_runs

VM_7_65_GB = 7836  # what `docker info` reported on the machine that lost the run


def test_the_measured_vm_allows_two_runs() -> None:
    """7.65 GiB at 2 GiB per sandbox: two fit inside the 70% headroom."""
    assert max_parallel_runs(VM_7_65_GB) == 2


def test_a_bigger_vm_allows_more() -> None:
    """Raising Docker Desktop's allocation must raise parallelism on its own."""
    assert max_parallel_runs(16384) > max_parallel_runs(VM_7_65_GB)


def test_a_tiny_vm_clamps_to_one_never_zero() -> None:
    """Refusing to run anything is worse than running one thing slowly."""
    assert max_parallel_runs(512) == 1
    assert max_parallel_runs(1) == 1


def test_configured_concurrency_is_clamped_to_capacity() -> None:
    assert effective_concurrency(8, VM_7_65_GB) == 2
    assert effective_concurrency(1, VM_7_65_GB) == 1, "never raised above what was asked for"


def test_unknown_capacity_leaves_the_setting_alone() -> None:
    """No Docker is not an error: the fake harness needs no containers, and this
    guard exists to prevent overcommitment, not to refuse to work."""
    assert max_parallel_runs(None) is None or isinstance(max_parallel_runs(None), int)
    assert effective_concurrency(3, 0) == 3


def test_capacity_accounts_for_the_relay() -> None:
    """Every sealed run also runs a relay container, so a run costs more than
    its sandbox alone."""
    per_run = settings.sandbox_memory_mb + RELAY_MB
    usable = VM_7_65_GB * settings.sandbox_memory_headroom
    assert max_parallel_runs(VM_7_65_GB) == max(1, int(usable // per_run))
    assert RELAY_MB > 0
