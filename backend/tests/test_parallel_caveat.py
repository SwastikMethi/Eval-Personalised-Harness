"""Results must say when durations were measured against competing runs.

Parallel runs share CPU, so DURATION-derived numbers (execution efficiency, 15%
of the score) become less comparable. Correctness, reliability and token counts
are unaffected — a caveat implying otherwise would cast false doubt on the very
scores it describes.

Overlap is now derived from each run's `started_at`/`completed_at` rather than
from a recorded `concurrency` counter. The counter was `len(self._active)`, and
a finishing run's asyncio task lingers in that dict until its done-callback
fires — so a strictly serial matrix reported "2 runs in parallel" and the
generated summary repeated the claim. These tests therefore express overlap as
time, which is what the claim is actually about.
"""

from datetime import UTC, datetime, timedelta

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

T0 = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def experiment_with(windows: list[tuple[int, int] | None]) -> str:
    """Each window is (start, end) in seconds from T0. None means no timestamps."""
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
        for i, window in enumerate(windows, start=1):
            session.add(
                BenchmarkRun(
                    combination_id=combo.id, repetition=i,
                    idempotency_key=f"{combo.id}:{i}", state=RunState.COMPLETED,
                    started_at=at(window[0]) if window else None,
                    completed_at=at(window[1]) if window else None,
                    result={"score": 0.5},
                )
            )
        session.commit()
        return exp.id


def caveats_for(exp_id: str) -> list[str]:
    with SessionLocal() as session:
        return _parallel_caveat(session, exp_id)


def test_a_serial_matrix_gets_no_caveat() -> None:
    """Back-to-back runs. This is the case the old counter got wrong."""
    assert caveats_for(experiment_with([(0, 60), (60, 120), (120, 180)])) == []


def test_parallel_runs_are_declared_with_the_peak() -> None:
    # Three alive at once between 40s and 50s.
    [caveat] = caveats_for(experiment_with([(0, 100), (30, 80), (40, 50)]))
    assert "3 runs executing in parallel" in caveat


def test_the_caveat_limits_itself_to_durations() -> None:
    """It must not imply the correctness scores are suspect."""
    [caveat] = caveats_for(experiment_with([(0, 100), (50, 150)]))
    assert "execution-efficiency" in caveat
    assert "correctness, reliability and token counts are unaffected" in caveat


def test_a_run_without_timestamps_counts_as_serial() -> None:
    """Runs recorded before these columns were populated must not fabricate a
    caveat — an unknown overlap is not evidence of one."""
    assert caveats_for(experiment_with([None, None])) == []


def test_a_run_still_in_flight_does_not_fabricate_overlap() -> None:
    """A started-but-unfinished run has no window to compare."""
    exp_id = experiment_with([(0, 60), None])
    with SessionLocal() as session:
        combo = session.scalars(
            select(ExperimentCombination).where(ExperimentCombination.experiment_id == exp_id)
        ).first()
        run = session.scalars(
            select(BenchmarkRun)
            .where(BenchmarkRun.combination_id == combo.id)  # type: ignore[union-attr]
            .where(BenchmarkRun.started_at.is_(None))
        ).first()
        run.started_at = at(30)  # type: ignore[union-attr]
        session.commit()
    assert caveats_for(exp_id) == []
