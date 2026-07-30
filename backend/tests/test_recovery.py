from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.errors import ErrorCategory
from app.db.engine import SessionLocal
from app.models import Base, BenchmarkRun
from app.models.core import RunState
from app.orchestration.recovery import mark_stale_runs_failed, sweep_orphan_containers


def _make_combo(session) -> str:  # type: ignore[no-untyped-def]
    from app.models import BenchmarkTask, Experiment, ExperimentCombination, Repository

    repo = Repository(name="r", source="local", path_or_url="/tmp/r")
    session.add(repo)
    session.flush()
    task = BenchmarkTask(repository_id=repo.id, kind="user_defined", title="t", prompt="p")
    exp = Experiment(repository_id=repo.id, name="e")
    session.add_all([task, exp])
    session.flush()
    combo = ExperimentCombination(
        experiment_id=exp.id, task_id=task.id, harness="fake", provider="fake", model_id="m"
    )
    session.add(combo)
    session.flush()
    return str(combo.id)


def test_stale_runs_marked_failed_crash() -> None:
    from app.db.engine import engine

    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        combo_id = _make_combo(session)

        def make_run(state: RunState, key: str) -> BenchmarkRun:
            return BenchmarkRun(combination_id=combo_id, idempotency_key=key, state=state)

        stale = make_run(RunState.RUNNING, "rec-1")
        pending = make_run(RunState.PENDING, "rec-2")
        done = make_run(RunState.COMPLETED, "rec-3")
        session.add_all([stale, pending, done])
        session.commit()
        stale_id, pending_id, done_id = stale.id, pending.id, done.id

    count = mark_stale_runs_failed(SessionLocal)
    assert count >= 1

    with SessionLocal() as session:
        assert session.get(BenchmarkRun, stale_id).state == RunState.FAILED  # type: ignore[union-attr]
        assert (
            session.get(BenchmarkRun, stale_id).error_category  # type: ignore[union-attr]
            == ErrorCategory.CRASH
        )
        assert session.get(BenchmarkRun, pending_id).state == RunState.PENDING  # type: ignore[union-attr]
        assert session.get(BenchmarkRun, done_id).state == RunState.COMPLETED  # type: ignore[union-attr]
        # crash-failed runs are retryable
        assert QueueWorkerRetryable(stale_id)


def QueueWorkerRetryable(run_id: str) -> bool:
    from app.orchestration.queue import QueueWorker

    with SessionLocal() as session:
        return QueueWorker.retry_run(session, run_id)


def test_orphan_container_sweep_uses_labels() -> None:
    container = SimpleNamespace(labels={"aso.run_id": "r1"}, remove=MagicMock())
    client = MagicMock()
    client.containers.list.return_value = [container]
    client.networks.list.return_value = []

    removed = sweep_orphan_containers(client)

    client.containers.list.assert_called_once_with(all=True, filters={"label": "aso.run_id"})
    container.remove.assert_called_once_with(force=True)
    assert removed == ["r1"]
