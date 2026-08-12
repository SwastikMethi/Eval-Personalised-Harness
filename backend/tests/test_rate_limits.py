"""Rate limiting, cost accrual, and tool-call passthrough (spec §12, §14, §30.24).

Free-tier OpenRouter allows ~50 model requests per day, so throttling is the
ordinary path, not an edge case. A 429 that lands as FAILED would both lose the
run and poison the reliability statistics with a failure the agent never caused.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.api import proxy
from app.core.errors import ErrorCategory
from app.db.engine import SessionLocal
from app.models import BenchmarkRun, BenchmarkTask, Experiment, ExperimentCombination, Repository
from app.models.core import RunState
from app.orchestration.queue import QueueWorker
from app.providers.base import CompletionResult, CompletionUsage, ModelInfo, ModelProvider
from app.providers.fake import FakeProvider
from app.providers.openrouter import ProviderError

MODEL = "fake/deterministic-1:free"


class ThrottlingProvider(ModelProvider):
    name = "throttling"

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def validate_model(self, model_id: str) -> ModelInfo:
        raise NotImplementedError

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": False}

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        raise ProviderError(
            "rate limited (429)", ErrorCategory.RATE_LIMITED, retryable=True, status=429
        )


class ToolCallingProvider(ModelProvider):
    """Records what it was handed and answers with a tool call."""

    name = "toolcalling"
    seen: dict[str, Any] = {}

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def validate_model(self, model_id: str) -> ModelInfo:
        raise NotImplementedError

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True}

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        ToolCallingProvider.seen = dict(kwargs)
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "edit_file", "arguments": '{"path":"a.py"}'},
                }
            ],
        }
        return CompletionResult(
            content="",
            usage=CompletionUsage(input_tokens=10, output_tokens=5, cached_tokens=0),
            raw={},
            message=message,
            finish_reason="tool_calls",
        )


@pytest.fixture
def restore_provider() -> Iterator[None]:
    yield
    proxy.set_provider(FakeProvider())


def _make_run(state: RunState = RunState.RUNNING) -> str:
    with SessionLocal() as session:
        repo = Repository(name="rl", source="local", path_or_url="/tmp/rl")
        session.add(repo)
        session.flush()
        task = BenchmarkTask(repository_id=repo.id, kind="user_defined", title="t", prompt="p")
        exp = Experiment(repository_id=repo.id, name="rl")
        session.add_all([task, exp])
        session.flush()
        combo = ExperimentCombination(
            experiment_id=exp.id, task_id=task.id, harness="fake", provider="fake", model_id=MODEL
        )
        session.add(combo)
        session.flush()
        run = BenchmarkRun(
            combination_id=combo.id,
            repetition=1,
            state=state,
            idempotency_key=f"{combo.id}:1",
        )
        session.add(run)
        session.commit()
        return run.id


# --- proxy ------------------------------------------------------------------


async def test_proxy_returns_429_and_flags_the_run(restore_provider: None) -> None:
    proxy.set_provider(ThrottlingProvider())
    token = proxy.issue_run_token("rl-run", MODEL, max_requests=5)
    body = proxy.ChatRequest(model=MODEL, messages=[{"role": "user", "content": "hi"}])

    with pytest.raises(Exception) as exc:
        await proxy.chat_completions(body, authorization=f"Bearer {token}")
    assert getattr(exc.value, "status_code", None) == 429

    # The orchestrator reads this instead of parsing harness error strings.
    assert proxy.run_usage("rl-run")["rate_limited"] is True
    proxy.revoke_run_token("rl-run")


async def test_cost_accrues_so_the_spend_ceiling_can_fire(restore_provider: None) -> None:
    proxy.set_provider(FakeProvider())
    token = proxy.issue_run_token(
        "cost-run",
        MODEL,
        max_requests=10,
        max_cost_usd=0.000_01,
        input_price=1e-6,
        output_price=2e-6,
    )
    body = proxy.ChatRequest(model=MODEL, messages=[{"role": "user", "content": "one two three"}])
    await proxy.chat_completions(body, authorization=f"Bearer {token}")

    usage = proxy.run_usage("cost-run")
    # Previously prices were never passed, so this stayed 0.0 forever and the
    # ceiling was unreachable no matter how much was spent.
    assert usage["cost_usd"] > 0

    with pytest.raises(Exception) as exc:
        await proxy.chat_completions(body, authorization=f"Bearer {token}")
    assert getattr(exc.value, "status_code", None) == 429
    proxy.revoke_run_token("cost-run")


async def test_a_fake_run_stays_on_the_fake_provider(restore_provider: None) -> None:
    """With a real key configured the proxy used to send EVERYTHING upstream,
    so the zero-cost fake path broke the moment a key existed."""
    proxy.set_provider(ThrottlingProvider())  # stands in for "the real provider"
    token = proxy.issue_run_token("fake-run", MODEL, max_requests=3, provider="fake")
    body = proxy.ChatRequest(model=MODEL, messages=[{"role": "user", "content": "hi"}])

    response = await proxy.chat_completions(body, authorization=f"Bearer {token}")
    assert "FAKE_COMPLETION" in response["choices"][0]["message"]["content"]
    assert proxy.run_usage("fake-run")["rate_limited"] is False
    proxy.revoke_run_token("fake-run")


async def test_tool_definitions_reach_provider_and_tool_calls_come_back(
    restore_provider: None,
) -> None:
    proxy.set_provider(ToolCallingProvider())
    token = proxy.issue_run_token("tool-run", MODEL, max_requests=5)
    tools = [{"type": "function", "function": {"name": "edit_file", "parameters": {}}}]
    body = proxy.ChatRequest(
        model=MODEL,
        messages=[{"role": "user", "content": "edit it"}],
        tools=tools,
        tool_choice="auto",
    )
    response = await proxy.chat_completions(body, authorization=f"Bearer {token}")

    assert ToolCallingProvider.seen["tools"] == tools
    assert ToolCallingProvider.seen["tool_choice"] == "auto"

    choice = response["choices"][0]
    # The old proxy rebuilt the message from `content` and hardcoded "stop",
    # which makes a harness think the model answered when it asked for a tool.
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "edit_file"
    assert choice["finish_reason"] == "tool_calls"
    proxy.revoke_run_token("tool-run")


# --- queue ------------------------------------------------------------------


def test_rate_limited_run_is_parked_with_a_backoff_then_released() -> None:
    worker = QueueWorker(SessionLocal, proxy_base_url="http://test/proxy")
    run_id = _make_run(RunState.RUNNING)

    worker._rate_limit(run_id, {"requests": 3, "rate_limited": True})

    with SessionLocal() as session:
        run = session.get(BenchmarkRun, run_id)
        assert run is not None
        assert RunState(run.state) is RunState.RATE_LIMITED
        assert run.error_category == ErrorCategory.RATE_LIMITED
        assert run.retry_after is not None

    # Still parked while the backoff is in the future.
    worker._release_rate_limited()
    with SessionLocal() as session:
        assert RunState(session.get(BenchmarkRun, run_id).state) is RunState.RATE_LIMITED  # type: ignore[union-attr]

    # Once the deadline passes it returns to PENDING and can be claimed again.
    with SessionLocal() as session:
        run = session.get(BenchmarkRun, run_id)
        run.retry_after = datetime.now(UTC) - timedelta(seconds=1)  # type: ignore[union-attr]
        session.commit()
    worker._release_rate_limited()
    with SessionLocal() as session:
        run = session.get(BenchmarkRun, run_id)
        assert RunState(run.state) is RunState.PENDING  # type: ignore[union-attr]
        assert run.retry_after is None  # type: ignore[union-attr]


def test_slow_provider_reads_as_timeout_not_a_broken_harness() -> None:
    """Requests all succeeded upstream but the harness got no output — the
    client gave up on a slow provider. Execution efficiency is 15% of the
    score, so slowness must land as a measurement, not a crash."""
    from types import SimpleNamespace

    worker = QueueWorker(SessionLocal, proxy_base_url="http://test/proxy")
    failed = SimpleNamespace(status="failed")

    assert worker._looks_like_provider_timeout(
        failed, {"requests": 6, "succeeded": 6, "failed_requests": 0}
    )
    # A harness that never reached the provider is genuinely broken.
    assert not worker._looks_like_provider_timeout(
        failed, {"requests": 0, "succeeded": 0, "failed_requests": 0}
    )
    # So is one whose requests errored upstream.
    assert not worker._looks_like_provider_timeout(
        failed, {"requests": 4, "succeeded": 0, "failed_requests": 4}
    )
    # A completed run is never a timeout.
    assert not worker._looks_like_provider_timeout(
        SimpleNamespace(status="completed"),
        {"requests": 6, "succeeded": 6, "failed_requests": 0},
    )


def test_a_completed_run_that_never_reached_the_model_is_not_success() -> None:
    """Observed: mini-swe-agent exited 0 with 10 upstream requests, ALL failed,
    zero agent steps and no patch — and the run was recorded COMPLETED. A run
    that never ran must not count as a working combination."""
    from types import SimpleNamespace

    worker = QueueWorker(SessionLocal, proxy_base_url="http://test/proxy")
    nothing = SimpleNamespace(status="completed", agent_steps=0, patch=None)

    assert worker._did_no_work(nothing, {"requests": 10, "succeeded": 0})

    # An empty patch after real work is a legitimate result, not a failure.
    tried = SimpleNamespace(status="completed", agent_steps=7, patch=None)
    assert not worker._did_no_work(tried, {"requests": 6, "succeeded": 6})
    # A patch is proof of work even if the step count is unreported.
    patched = SimpleNamespace(status="completed", agent_steps=0, patch="diff --git a b")
    assert not worker._did_no_work(patched, {"requests": 0, "succeeded": 0})


def test_unreachable_proxy_is_not_reported_as_a_slow_provider() -> None:
    """The shape that produced a fabricated latency claim.

    The proxy was bound to loopback, so the relay could not reach it: the
    token counter had incremented on authorize, but no request ever reached a
    provider and no metric row was written. Asking only `failed_requests == 0`
    was trivially true, and the run was filed as "1 upstream requests all
    succeeded" — a latency story invented for a connection failure.
    """
    from types import SimpleNamespace

    worker = QueueWorker(SessionLocal, proxy_base_url="http://test/proxy")
    run_id = _make_run(RunState.RUNNING)

    # No ModelRequestMetric rows exist for this run — nothing reached upstream.
    usage = worker._persisted_usage(run_id, {"requests": 1, "rate_limited": False})

    assert usage["succeeded"] == 0
    assert not worker._looks_like_provider_timeout(SimpleNamespace(status="failed"), usage), (
        "no recorded 200 means no evidence the provider ever answered"
    )


def test_usage_accumulates_across_attempts() -> None:
    """The run token is reissued per attempt, so its counter reported only the
    LAST attempt while every attempt had spent quota — making
    max_model_requests a per-attempt cap that under-reported real spend."""
    from app.models import ModelRequestMetric

    worker = QueueWorker(SessionLocal, proxy_base_url="http://test/proxy")
    run_id = _make_run(RunState.RUNNING)
    with SessionLocal() as session:
        for _attempt in range(2):
            for _ in range(3):
                session.add(
                    ModelRequestMetric(
                        run_id=run_id, model_id=MODEL, http_status=200,
                        input_tokens=100, output_tokens=50,
                    )
                )
        session.commit()

    # The live token believes only the second attempt happened.
    live = {"requests": 3, "input_tokens": 300, "output_tokens": 150, "rate_limited": False}
    merged = worker._persisted_usage(run_id, live)

    assert merged["requests"] == 6, "must count every attempt, not just the last"
    assert merged["input_tokens"] == 600
    assert merged["output_tokens"] == 300
    # Live-only flags survive: they describe the attempt that just ran.
    assert merged["rate_limited"] is False


def test_backoff_lengthens_with_repeated_throttling() -> None:
    worker = QueueWorker(SessionLocal, proxy_base_url="http://test/proxy")
    run_id = _make_run(RunState.RUNNING)
    delays = []

    for _ in range(3):
        worker._rate_limit(run_id, {"rate_limited": True})
        with SessionLocal() as session:
            run = session.get(BenchmarkRun, run_id)
            assert run is not None
            delays.append(run.retry_after)
            run.state = RunState.RUNNING  # re-arm for the next round
            run.retry_after = None
            session.commit()

    from app.models import RunEvent

    with SessionLocal() as session:
        events = session.scalars(
            select(RunEvent).where(
                RunEvent.run_id == run_id, RunEvent.event_type == "rate_limited"
            )
        ).all()
    assert len(events) == 3
    # Escalating, because retrying sooner just re-spends a daily quota.
    assert [e.payload["retry_in_s"] for e in events] == [30.0, 120.0, 600.0]
