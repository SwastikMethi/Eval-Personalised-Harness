"""Container tests must not run while a benchmark run is in flight.

This suite has destroyed a user's run twice. It churns enough Docker containers
to put the daemon under pressure, and the kernel kills whatever it likes —
including the live run's agent and relay:

    aso-relay-b4f679c3eb19  exit=137   <- the user's run
    aso-relay-t-seal        exit=137   <- this suite

The `docker` marker exists so those tests can be deselected, and both times the
protection failed because it depended on whoever typed the command remembering
to use it. The guard is automatic now, so these tests cover the logic it uses.
"""

import sqlite3
from pathlib import Path

from tests.conftest import active_run


def db_with(tmp_path: Path, rows: list[tuple[str, str]]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "aso.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE benchmark_runs (id TEXT PRIMARY KEY, state TEXT)")
    conn.executemany("INSERT INTO benchmark_runs (id, state) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()
    return path


def test_a_running_benchmark_is_detected(tmp_path: Path) -> None:
    path = db_with(tmp_path, [("run-completed", "COMPLETED"), ("run-live", "RUNNING")])
    assert active_run(path) == ("run-live", "RUNNING")


def test_every_in_flight_state_counts(tmp_path: Path) -> None:
    """A run being prepared is just as killable as one mid-request."""
    for state in ("PENDING", "PREPARING", "RUNNING", "EVALUATING"):
        path = db_with(tmp_path / state, [(f"r-{state}", state)])
        assert active_run(path) is not None, state


def test_finished_runs_do_not_block_the_suite(tmp_path: Path) -> None:
    path = db_with(
        tmp_path,
        [("a", "COMPLETED"), ("b", "FAILED"), ("c", "CANCELLED"), ("d", "TIMED_OUT")],
    )
    assert active_run(path) is None


def test_a_missing_database_is_not_an_error(tmp_path: Path) -> None:
    """No database means no backend to disturb — and must never create one."""
    missing = tmp_path / "nope" / "aso.db"
    assert active_run(missing) is None
    assert not missing.exists()


def test_an_unreadable_database_does_not_block_the_suite(tmp_path: Path) -> None:
    """This guard protects a run; it must not become a way to fail CI."""
    junk = tmp_path / "aso.db"
    junk.write_text("not a database")
    assert active_run(junk) is None
