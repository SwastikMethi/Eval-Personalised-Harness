"""Startup crash reconciliation (eng review 2A).

If the backend dies mid-run it leaves (a) containers labeled aso.run_id that
nobody owns and (b) DB rows stuck in PREPARING/RUNNING/EVALUATING. On startup:
kill and remove the orphans, mark the stale rows FAILED(crash) — retryable.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import ErrorCategory
from app.models import BenchmarkRun
from app.models.core import RunState
from app.sandboxes.manager import RUN_LABEL

log = logging.getLogger(__name__)

_STALE_STATES = (RunState.PREPARING, RunState.RUNNING, RunState.EVALUATING)


def sweep_orphan_containers(docker_client: Any) -> list[str]:
    removed = []
    for container in docker_client.containers.list(all=True, filters={"label": RUN_LABEL}):
        run_id = container.labels.get(RUN_LABEL, "unknown")
        try:
            container.remove(force=True)
            removed.append(run_id)
        except Exception:  # noqa: BLE001 - best-effort sweep
            log.warning("failed to remove orphan container", extra={"run_id": run_id})
    for network in docker_client.networks.list(filters={"label": RUN_LABEL}):
        try:
            network.remove()
        except Exception:  # noqa: BLE001
            pass
    return removed


def mark_stale_runs_failed(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as session:
        stale = session.scalars(
            select(BenchmarkRun).where(BenchmarkRun.state.in_(_STALE_STATES))
        ).all()
        for run in stale:
            run.state = RunState.FAILED
            run.error_category = ErrorCategory.CRASH
            run.error_message = "backend restarted while run was active"
            run.completed_at = datetime.now(UTC)
        session.commit()
        return len(stale)


def reconcile(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Full startup sweep. Docker part is skipped gracefully when unavailable."""
    removed: list[str] = []
    try:
        import docker

        removed = sweep_orphan_containers(docker.from_env())
    except Exception:  # noqa: BLE001 - no docker at startup is not fatal
        log.info("docker unavailable during reconciliation — skipping container sweep")
    stale = mark_stale_runs_failed(session_factory)
    if removed or stale:
        log.info(
            "reconciliation complete",
            extra={"event_type": "reconciliation", "duration": None},
        )
    return {"orphan_containers_removed": len(removed), "stale_runs_failed": stale}
