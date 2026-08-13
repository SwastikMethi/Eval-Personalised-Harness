"""Preflight: prove a model is callable before a matrix is queued (spec §21).

deepseek-coder appeared in NIM's catalog, so the UI offered it, and the run
failed on its first request with "Not found for account". By then a workspace,
a prepared image, a container and a network seal had all been paid for. The
answer cost one token and half a second.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.errors import ErrorCategory
from app.providers import preflight
from app.providers.base import CompletionResult, CompletionUsage, ModelInfo, ModelProvider
from app.providers.openrouter import ProviderError


class Recording(ModelProvider):
    name = "recording"

    def __init__(self, fail_with: ProviderError | None = None) -> None:
        self.calls: list[str] = []
        self._fail = fail_with

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def validate_model(self, model_id: str) -> ModelInfo:
        raise NotImplementedError

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True}

    async def complete(
        self, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> CompletionResult:
        self.calls.append(model_id)
        if self._fail:
            raise self._fail
        return CompletionResult(
            content="ok",
            usage=CompletionUsage(input_tokens=1, output_tokens=1, cached_tokens=0),
            raw={},
            message={"role": "assistant", "content": "ok"},
            finish_reason="stop",
        )


def combo(provider: str, model_id: str) -> Any:
    return SimpleNamespace(provider=provider, model_id=model_id)


@pytest.fixture(autouse=True)
def _clear() -> None:
    preflight.clear_cache()


async def test_an_unusable_model_is_reported_with_its_reason() -> None:
    provider = Recording(
        ProviderError(
            "provider rejected request (404): Not found for account",
            ErrorCategory.MODEL_PROVIDER,
            retryable=False,
            status=404,
        )
    )
    [result] = await preflight.check_combinations(
        [combo("nvidia", "deepseek-ai/deepseek-coder-6.7b-instruct")], lambda _n: provider
    )
    assert not result.ok
    assert "Not found for account" in result.detail
    assert result.label == "nvidia/deepseek-ai/deepseek-coder-6.7b-instruct"


async def test_each_pair_is_probed_once_however_many_runs_use_it() -> None:
    """A 2x2 with 3 repetitions is 12 runs and 4 pairs. Probing per run would
    make preflight cost more than the thing it protects."""
    provider = Recording()
    combos = [combo("nvidia", "a"), combo("nvidia", "b"), combo("nvidia", "a")] * 3

    results = await preflight.check_combinations(combos, lambda _n: provider)

    assert len(results) == 2
    assert provider.calls == ["a", "b"]


async def test_distinct_models_are_probed_concurrently() -> None:
    """Serially, a 2-model matrix cost the sum of both probes — gpt-oss-120b
    measured 21s, so Start sat dead for ~40s. Wall time must be the slowest
    probe, not the total."""
    import asyncio
    import time

    DELAY = 0.25

    class Slow(Recording):
        async def complete(self, model_id: str, *a: Any, **k: Any) -> CompletionResult:
            self.calls.append(model_id)
            await asyncio.sleep(DELAY)
            return await Recording.complete(self, model_id, *a, **k)

    provider = Slow()
    combos = [combo("nvidia", f"m{i}") for i in range(4)]

    start = time.monotonic()
    results = await preflight.check_combinations(combos, lambda _n: provider)
    elapsed = time.monotonic() - start

    assert len(results) == 4
    assert elapsed < DELAY * 3, f"probes ran serially: {elapsed:.2f}s for 4 x {DELAY}s"


async def test_a_repeat_submission_uses_the_cache() -> None:
    provider = Recording()
    for _ in range(3):
        await preflight.check_combinations([combo("nvidia", "a")], lambda _n: provider)
    assert provider.calls == ["a"], "cached, so re-submitting a matrix costs nothing"


async def test_throttling_does_not_condemn_a_model() -> None:
    """A 429 means the model exists and we are being rate limited — the queue
    already parks and retries those. Refusing the experiment would be wrong."""
    provider = Recording(
        ProviderError("rate limited (429)", ErrorCategory.RATE_LIMITED, retryable=True, status=429)
    )
    [result] = await preflight.check_combinations([combo("nvidia", "a")], lambda _n: provider)
    assert result.ok
    assert "rate limited" in result.warning


async def test_a_gateway_timeout_does_not_condemn_a_working_model() -> None:
    """deepseek-v4-flash completed seven calls in one run and periodically 504s
    at NIM's ~302s gateway limit. Treating that transient as "unusable" would
    delete a working combination from the comparison."""
    provider = Recording(
        ProviderError(
            "provider error (504): ", ErrorCategory.MODEL_PROVIDER, retryable=True, status=504
        )
    )
    [result] = await preflight.check_combinations([combo("nvidia", "slow")], lambda _n: provider)

    assert result.ok, "a retryable upstream error is not an entitlement problem"
    assert "504" in result.warning


async def test_a_slow_model_is_usable_with_a_warning_not_a_refusal() -> None:
    """The probe must bound itself: without that, Start hung for minutes on a
    slow model and then wrongly refused it."""
    import asyncio
    import time

    class TooSlow(Recording):
        async def complete(self, *a: Any, **k: Any) -> CompletionResult:
            await asyncio.sleep(60)
            raise AssertionError("should have been cut off")

    original = preflight.PROBE_TIMEOUT_S
    preflight.PROBE_TIMEOUT_S = 0.25
    try:
        start = time.monotonic()
        [result] = await preflight.check_combinations(
            [combo("nvidia", "sluggish")], lambda _n: TooSlow()
        )
        elapsed = time.monotonic() - start
    finally:
        preflight.PROBE_TIMEOUT_S = original

    assert result.ok, "slow is not broken"
    assert "slow" in result.warning
    assert elapsed < 5, f"probe did not bound itself: {elapsed:.1f}s"


async def test_preflight_never_crashes_experiment_creation() -> None:
    class Exploding(Recording):
        async def complete(self, *a: Any, **k: Any) -> CompletionResult:
            raise RuntimeError("transport exploded")

    [result] = await preflight.check_combinations([combo("nvidia", "a")], lambda _n: Exploding())
    assert not result.ok
    assert "RuntimeError" in result.detail


async def test_creating_an_experiment_with_an_unusable_model_writes_no_runs() -> None:
    """Refusing the whole matrix beats queueing one with holes in it."""
    from sqlalchemy import func, select

    from app.api import proxy
    from app.api.routes import ExperimentIn, create_experiment
    from app.db.engine import SessionLocal
    from app.models import BenchmarkRun, BenchmarkTask, Experiment, Repository

    with SessionLocal() as session:
        repo = Repository(name="pf", source="local", path_or_url="/tmp/pf")
        session.add(repo)
        session.flush()
        task = BenchmarkTask(repository_id=repo.id, kind="user_defined", title="t", prompt="p")
        session.add(task)
        session.commit()
        repo_id, task_id = repo.id, task.id
        before = session.scalar(select(func.count()).select_from(BenchmarkRun))

    broken = Recording(
        ProviderError("provider rejected request (404): Not found", ErrorCategory.MODEL_PROVIDER,
                      retryable=False, status=404)
    )
    original = proxy.provider_for
    proxy.provider_for = lambda _n: broken  # type: ignore[assignment]
    try:
        with SessionLocal() as session:
            with pytest.raises(HTTPException) as exc:
                await create_experiment(
                    ExperimentIn(
                        repository_id=repo_id,
                        name="unusable",
                        task_ids=[task_id],
                        combinations=[
                            {"harness": "fake", "provider": "nvidia", "model_id": "gone"}
                        ],
                        repetitions=1,
                        config={},
                    ),
                    session=session,
                )
        assert exc.value.status_code == 422
        assert "nvidia/gone" in str(exc.value.detail)
    finally:
        proxy.provider_for = original  # type: ignore[assignment]

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(BenchmarkRun)) == before
        assert (
            session.scalars(select(Experiment).where(Experiment.name == "unusable")).first()
            is None
        ), "no half-created experiment left behind"
