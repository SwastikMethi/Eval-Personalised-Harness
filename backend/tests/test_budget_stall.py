"""A run that spends its budget must end, not hang until its timeout.

Observed: a run made 4 requests in 45 seconds, exhausted max_model_requests=4,
and then held its container for 7+ minutes with no further calls. Its 5th
request got `429 run request budget exceeded` — the same status a provider
sends when throttling — so the harness backed off and retried something that
would never succeed. Left alone it would have run to the 1800s timeout and been
recorded as TIMED_OUT, scoring an orderly end of budget as slowness when
execution efficiency is 15% of the score.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api import proxy
from app.core.errors import ErrorCategory
from app.db.engine import SessionLocal
from app.models import BenchmarkRun, ModelRequestMetric
from app.models.core import RunState
from app.orchestration.queue import BUDGET_STALL_GRACE_S, QueueWorker
from tests.test_rate_limits import MODEL, _make_run


def worker() -> QueueWorker:
    return QueueWorker(SessionLocal, proxy_base_url="http://test/proxy")


def metric_at(run_id: str, when: datetime) -> None:
    with SessionLocal() as session:
        session.add(
            ModelRequestMetric(
                run_id=run_id, model_id=MODEL, http_status=200,
                input_tokens=10, output_tokens=10, created_at=when,
            )
        )
        session.commit()


# --- the wire signal --------------------------------------------------------


async def test_budget_refusal_is_marked_terminal() -> None:
    """A rate limit says "later"; a spent budget says "never, for this run".
    They must not look identical to a harness."""
    proxy.set_provider(proxy.FakeProvider())
    token = proxy.issue_run_token("terminal-run", MODEL, max_requests=1)
    body = proxy.ChatRequest(model=MODEL, messages=[{"role": "user", "content": "hi"}])

    await proxy.chat_completions(body, authorization=f"Bearer {token}")

    with pytest.raises(HTTPException) as exc:
        await proxy.chat_completions(body, authorization=f"Bearer {token}")

    assert exc.value.status_code == 429
    assert (exc.value.headers or {}).get(proxy.TERMINAL_HEADER) == proxy.BUDGET_EXHAUSTED
    assert "do not retry" in str(exc.value.detail)
    proxy.revoke_run_token("terminal-run")


# --- the watchdog -----------------------------------------------------------


def test_a_spent_budget_gone_quiet_is_stalled() -> None:
    run_id = _make_run(RunState.RUNNING)
    proxy.issue_run_token(run_id, MODEL, max_requests=1)
    now = datetime.now(UTC).replace(tzinfo=None)
    metric_at(run_id, now - timedelta(seconds=BUDGET_STALL_GRACE_S + 30))
    # Spend the budget so the token reports exhausted.
    proxy._active_tokens[run_id].requests = 1

    assert run_id in worker()._stalled_budget_runs(now)
    proxy.revoke_run_token(run_id)


def test_a_slow_model_is_not_mistaken_for_a_stalled_run() -> None:
    """Live calls have taken 65s. A run mid-request must be left alone."""
    run_id = _make_run(RunState.RUNNING)
    proxy.issue_run_token(run_id, MODEL, max_requests=1)
    now = datetime.now(UTC).replace(tzinfo=None)
    metric_at(run_id, now - timedelta(seconds=BUDGET_STALL_GRACE_S - 30))
    proxy._active_tokens[run_id].requests = 1

    assert run_id not in worker()._stalled_budget_runs(now)
    proxy.revoke_run_token(run_id)


def test_a_run_with_budget_left_is_never_ended() -> None:
    """Silence alone is not grounds — only silence AFTER the budget is spent."""
    run_id = _make_run(RunState.RUNNING)
    proxy.issue_run_token(run_id, MODEL, max_requests=10)
    now = datetime.now(UTC).replace(tzinfo=None)
    metric_at(run_id, now - timedelta(seconds=BUDGET_STALL_GRACE_S + 600))
    proxy._active_tokens[run_id].requests = 1

    assert run_id not in worker()._stalled_budget_runs(now)
    proxy.revoke_run_token(run_id)


async def test_ending_a_stalled_run_reports_budget_not_timeout() -> None:
    """TIMED_OUT would feed the efficiency score a slowness that never happened."""
    run_id = _make_run(RunState.RUNNING)
    proxy.issue_run_token(run_id, MODEL, max_requests=1)
    proxy._active_tokens[run_id].requests = 1
    metric_at(run_id, datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=600))

    await worker()._end_stalled_budget_runs()

    with SessionLocal() as session:
        run = session.get(BenchmarkRun, run_id)
        assert run is not None
        assert RunState(run.state) is RunState.FAILED
        assert run.error_category == ErrorCategory.BUDGET_EXCEEDED
        assert RunState(run.state) is not RunState.TIMED_OUT
    proxy.revoke_run_token(run_id)
