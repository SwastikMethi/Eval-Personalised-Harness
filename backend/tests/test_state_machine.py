import pytest

from app.models import BenchmarkRun
from app.models.core import VALID_TRANSITIONS, RunState
from app.orchestration.queue import transition


def make_run(state: RunState) -> BenchmarkRun:
    return BenchmarkRun(combination_id="c", idempotency_key="k", state=state)


def test_happy_path() -> None:
    run = make_run(RunState.PENDING)
    for state in (
        RunState.PREPARING,
        RunState.RUNNING,
        RunState.EVALUATING,
        RunState.COMPLETED,
    ):
        transition(run, state)
    assert run.state == RunState.COMPLETED


def test_invalid_transition_rejected() -> None:
    run = make_run(RunState.PENDING)
    with pytest.raises(ValueError, match="invalid transition"):
        transition(run, RunState.COMPLETED)


def test_completed_is_terminal() -> None:
    assert VALID_TRANSITIONS[RunState.COMPLETED] == set()


def test_failed_and_timeout_are_retryable() -> None:
    assert RunState.PENDING in VALID_TRANSITIONS[RunState.FAILED]
    assert RunState.PENDING in VALID_TRANSITIONS[RunState.TIMED_OUT]


def test_evaluating_can_end_in_timeout() -> None:
    """Every run is evaluated regardless of how the harness ended — a timed-out
    agent may still have left a partial patch worth grading — so the terminal
    state is set FROM evaluating. Without this the timeout branch raised
    "invalid transition" and every slow-provider failure was recorded as a
    generic harness crash.
    """
    run = make_run(RunState.PENDING)
    for state in (RunState.PREPARING, RunState.RUNNING, RunState.EVALUATING):
        transition(run, state)
    transition(run, RunState.TIMED_OUT)
    assert run.state == RunState.TIMED_OUT


def test_rate_limited_requeues() -> None:
    assert RunState.PENDING in VALID_TRANSITIONS[RunState.RATE_LIMITED]
