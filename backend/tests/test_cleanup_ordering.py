"""The agent's container must be released before grading starts.

It used to be held until the `finally`, so the agent container and the evaluation
container — each permitted SandboxLimits.memory_mb — coexisted. At the old 4 GiB
limit on a 7.65 GiB Docker VM that overcommitted the VM, and runs were killed
with `exit 137, oom_killed=False`. One lost 28 successful model calls at the
final patch-extraction step.

The patch is already extracted by then and evaluation deliberately rebuilds a
fresh snapshot, so the agent container is dead weight during grading.
"""

import inspect

from app.orchestration.queue import QueueWorker


def test_the_sandbox_is_released_before_evaluation_is_invoked() -> None:
    """Asserted on the source order because the alternative — driving a whole
    sandboxed run — needs Docker, and this is a sequencing guarantee."""
    src = inspect.getsource(QueueWorker._execute)

    cleanup_at = src.find("self._sandboxes.cleanup(run_id)")
    evaluate_at = src.find("self._evaluate, run_id, task_id, result.patch")

    assert cleanup_at != -1, "the agent sandbox must be cleaned up in _execute"
    assert evaluate_at != -1
    assert cleanup_at < evaluate_at, (
        "evaluation starts a second container; releasing the agent's only "
        "afterwards overcommits the Docker VM"
    )


def test_cleanup_is_idempotent_so_the_finally_stays_a_safety_net() -> None:
    """Cleanup now runs twice on the happy path. A second call must be harmless,
    or the safety net becomes the failure."""
    from app.sandboxes.manager import SandboxManager

    m = SandboxManager()
    src = inspect.getsource(SandboxManager.cleanup)
    # pop() with a default is what makes the repeat call a no-op.
    assert "pop(run_id, None)" in src
    assert m._containers == {}


def test_the_run_records_the_concurrency_it_executed_under() -> None:
    src = inspect.getsource(QueueWorker._execute)
    assert '"concurrency": peak_concurrency' in src
    assert "started_concurrency = max(len(self._active), 1)" in src
