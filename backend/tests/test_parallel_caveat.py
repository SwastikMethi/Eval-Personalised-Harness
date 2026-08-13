"""Results must say when durations were measured against competing runs.

Parallel runs share CPU, so DURATION-derived numbers (execution efficiency, 15%
of the score) become less comparable. Correctness, reliability and token counts
are unaffected — a caveat implying otherwise would cast false doubt on the very
scores it describes.
"""

from sqlalchemy import select

from app.api.results_api import _parallel_caveat
from app.db.engine import SessionLocal
from app.models import (
    BenchmarkRun,
    BenchmarkTask,
    Experiment,
    ExperimentCombination,
    Repository,
)
from app.models.core import RunState


def experiment_with(concurrencies: list[int]) -> str:
    with SessionLocal() as session:
        repo = Repository(name="pc", source="local", path_or_url="/tmp/pc")
        session.add(repo)
        session.flush()
        task = BenchmarkTask(repository_id=repo.id, kind="user_defined", title="t", prompt="p")
        exp = Experiment(repository_id=repo.id, name="parallel-caveat")
        session.add_all([task, exp])
        session.flush()
        combo = ExperimentCombination(
            experiment_id=exp.id, task_id=task.id, harness="fake",
            provider="fake", model_id="m",
        )
        session.add(combo)
        session.flush()
        for i, c in enumerate(concurrencies, start=1):
            session.add(
                BenchmarkRun(
                    combination_id=combo.id, repetition=i,
                    idempotency_key=f"{combo.id}:{i}", state=RunState.COMPLETED,
                    result={"concurrency": c, "score": 0.5},
                )
            )
        session.commit()
        return exp.id


def caveats_for(exp_id: str) -> list[str]:
    with SessionLocal() as session:
        return _parallel_caveat(session, exp_id)


def test_a_serial_matrix_gets_no_caveat() -> None:
    assert caveats_for(experiment_with([1, 1, 1])) == []


def test_parallel_runs_are_declared_with_the_peak() -> None:
    [caveat] = caveats_for(experiment_with([1, 3, 2]))
    assert "3 runs executing in parallel" in caveat


def test_the_caveat_limits_itself_to_durations() -> None:
    """It must not imply the correctness scores are suspect."""
    [caveat] = caveats_for(experiment_with([2]))
    assert "execution-efficiency" in caveat
    assert "correctness, reliability and token counts are unaffected" in caveat


def test_a_run_without_the_field_counts_as_serial() -> None:
    """Runs recorded before this field existed must not fabricate a caveat."""
    with SessionLocal() as session:
        exp_id = experiment_with([1])
        combo = session.scalars(
            select(ExperimentCombination).where(ExperimentCombination.experiment_id == exp_id)
        ).first()
        run = session.scalars(
            select(BenchmarkRun).where(BenchmarkRun.combination_id == combo.id)  # type: ignore[union-attr]
        ).first()
        run.result = {"score": 0.5}  # type: ignore[union-attr]
        session.commit()
    assert caveats_for(exp_id) == []
