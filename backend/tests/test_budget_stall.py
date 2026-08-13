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


class SandboxWithPatch:
    """Stands in for the live container, which still holds the agent's work."""

    def __init__(self, patch: str = "") -> None:
        self.patch = patch
        self.killed = False

    async def exec(self, run_id: str, command: str, timeout_s: int = 600):  # type: ignore[no-untyped-def]
        from app.sandboxes.exec import CommandResult

        stdout = self.patch if "git diff --cached" in command else ""
        return CommandResult(command=command, exit_code=0, stdout=stdout, stderr="", duration_s=0.1)

    async def kill(self, run_id: str) -> None:
        self.killed = True

    async def cleanup(self, run_id: str) -> None: ...


async def test_a_spent_budget_keeps_the_patch_the_agent_produced(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The defect this replaces: the watchdog killed the container and stored an
    empty result, so a real run lost 8 successful model calls of work — no
    patch, no usage, no score, indistinguishable from an agent that did nothing.
    At a 40-request budget that is half an hour of credits discarded."""
    run_id = _make_run(RunState.RUNNING)
    proxy.issue_run_token(run_id, MODEL, max_requests=1)
    proxy._active_tokens[run_id].requests = 1
    metric_at(run_id, datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=600))

    patch = "diff --git a/app.py b/app.py\n+fixed\n"
    w = QueueWorker(SessionLocal, proxy_base_url="http://test/proxy",
                    sandbox_manager=SandboxWithPatch(patch))
    # Grading runs in a container in production; here we only care that the
    # watchdog asks for it and records what it returns.
    monkeypatch.setattr(
        QueueWorker, "_evaluate", lambda *a, **k: {"signal": "ok", "score": 0.75}
    )

    await w._end_budget_run(run_id)

    with SessionLocal() as session:
        run = session.get(BenchmarkRun, run_id)
        assert run is not None
        assert RunState(run.state) is RunState.COMPLETED, "a patch means the run achieved something"
        assert run.result["patch_produced"] is True
        assert run.result["score"] == 0.75
        assert run.result["usage"]["requests"] >= 1, "what was spent must be recorded"
        assert run.result["agent_steps"] is None, "unknown, never a fabricated zero"
    proxy.revoke_run_token(run_id)


async def test_no_patch_still_fails_as_budget_exceeded(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    run_id = _make_run(RunState.RUNNING)
    proxy.issue_run_token(run_id, MODEL, max_requests=1)
    proxy._active_tokens[run_id].requests = 1
    metric_at(run_id, datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=600))

    w = QueueWorker(SessionLocal, proxy_base_url="http://test/proxy",
                    sandbox_manager=SandboxWithPatch(""))  # agent wrote nothing
    await w._end_budget_run(run_id)

    with SessionLocal() as session:
        run = session.get(BenchmarkRun, run_id)
        assert run is not None
        assert RunState(run.state) is RunState.FAILED
        assert run.error_category == ErrorCategory.BUDGET_EXCEEDED
        assert run.result["patch_produced"] is False
        assert run.result["usage"], "spend is recorded even when nothing was achieved"
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
