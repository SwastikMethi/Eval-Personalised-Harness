"""Run baseline and evaluation inside a container, with deps pre-installed.

One place for the prepared-image + container-executor dance so the baseline
endpoint and the queue's evaluation step cannot drift apart.

Falls back to host execution when Docker is unavailable, recording a warning
rather than failing: the tool should still work without Docker, it just has to
say that it is running in the mode where install and test can resolve to
different interpreters.
"""

import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.evaluators.engine import EvaluationContext, EvaluationOutcome, evaluate
from app.repositories.baseline import BaselineOutcome, run_baseline
from app.sandboxes.container_exec import ContainerExecutor
from app.sandboxes.exec import run_host_command
from app.sandboxes.manager import docker_available
from app.sandboxes.prepared import ensure_prepared_image

log = logging.getLogger(__name__)

HOST_FALLBACK_WARNING = (
    "Docker unavailable — commands ran on the host, where install and test can "
    "resolve to different interpreters. Results may be unreliable."
)


def prepared_image_for(root: Path, install_cmd: str | None, repo_id: str) -> tuple[str, Any]:
    """Image with this repo's dependencies baked in, plus the build result."""
    return ensure_prepared_image(root, install_cmd, repo_id)


def run_baseline_in_sandbox(
    workspace: Path,
    commands: dict[str, str | None],
    test_framework: str | None,
    repo_id: str,
) -> BaselineOutcome:
    if not docker_available():
        log.warning("baseline running on host: docker unavailable")
        outcome = run_baseline(workspace, commands, test_framework)
        outcome.steps["_warning"] = {"message": HOST_FALLBACK_WARNING}
        return outcome

    image, build = prepared_image_for(workspace, commands.get("install"), repo_id)
    with ContainerExecutor(workspace, image=image, label="baseline") as run:
        return run_baseline(
            workspace, commands, test_framework, execute=run, prebuilt_install=build
        )


def evaluate_in_sandbox(
    context: EvaluationContext, workdir: Path, repo_id: str, install_cmd: str | None
) -> EvaluationOutcome:
    """Grade a patch inside a container.

    Evaluation executes the AGENT's patch, so containerising it is a security
    improvement over running that on the host — quite apart from fixing the
    interpreter mismatch.
    """
    if not docker_available():
        log.warning("evaluation running on host: docker unavailable")
        outcome = evaluate(context, workdir, execute=run_host_command)
        outcome.results["_warning"] = {"message": HOST_FALLBACK_WARNING}
        return outcome

    image, _ = prepared_image_for(context.snapshot_source, install_cmd, repo_id)
    # evaluate() copies the snapshot into workdir/"graded"; the executor must
    # therefore mount workdir, not the pristine snapshot.
    workdir.mkdir(parents=True, exist_ok=True)
    with ContainerExecutor(workdir, image=image, label="eval") as run:
        return evaluate(context, workdir, execute=run)


__all__ = [
    "evaluate_in_sandbox",
    "prepared_image_for",
    "run_baseline_in_sandbox",
    "settings",
]
