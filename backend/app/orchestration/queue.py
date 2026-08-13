"""In-process asyncio queue worker (spec §13) behind a small interface.

Single-scheduler guard (eng review Tension 5): the worker refuses to start
twice in one process; `make dev` runs uvicorn without --workers so exactly
one scheduler exists. Concurrency is a semaphore (default 1, configurable).

Pipeline per run:
  PENDING → PREPARING (workspace snapshot; docker create+seal for sandboxed
            harnesses) → RUNNING (harness, proxy token issued) → EVALUATING
            (skeleton evaluator: patch produced?) → COMPLETED / FAILED
Pause = stop claiming new runs only (eng review Tension 5). Cancel kills the
container and marks CANCELLED. FAILED/TIMED_OUT retry back to PENDING.
"""

import asyncio
import hashlib
import logging
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.proxy import issue_run_token, revoke_run_token, run_usage
from app.core.config import settings
from app.core.errors import ErrorCategory
from app.harnesses.base import HarnessRunRequest, get_harness
from app.models import (
    Artifact,
    BenchmarkRun,
    BenchmarkTask,
    Experiment,
    ExperimentCombination,
    HiddenTestCandidate,
    ModelRequestMetric,
    ModelSnapshot,
    Repository,
    RunEvent,
)
from app.models.core import TERMINAL_STATES, VALID_TRANSITIONS, RunState
from app.repositories import service

log = logging.getLogger(__name__)

SANDBOXED_HARNESSES = {"mini-swe-agent", "smolagents"}

# Free-tier OpenRouter allows roughly 50 model requests per DAY without
# credits, so a generous per-run budget burns the whole quota on one run.
# See vault/05-decisions/ADR-003 Free Tier Constraints.md.
DEFAULT_MAX_MODEL_REQUESTS = 8

# Backoff before a RATE_LIMITED run returns to PENDING. Capped because the
# limit that matters is daily: retrying sooner just re-spends the quota.
def _category_for(exc: BaseException) -> ErrorCategory:
    """Whose fault was this failure?

    Everything used to be filed as HARNESS, so a container Docker killed, a
    network that vanished, or a failed seal was recorded as a harness crash.
    Harness reliability is the product's central metric — booking sandbox
    faults against whichever harness happened to be scheduled makes that metric
    a measure of Docker's mood. SETUP already exists for exactly this
    ("repo/sandbox/dependency failure").
    """
    from app.sandboxes.manager import SandboxError

    if isinstance(exc, SandboxError):
        return ErrorCategory.SETUP
    try:  # docker is optional at runtime, as in recovery.reconcile()
        from docker.errors import DockerException
    except ImportError:
        return ErrorCategory.HARNESS
    # 409 "container is not running", 404 "network not found" — infrastructure
    # the harness neither caused nor could have prevented.
    return ErrorCategory.SETUP if isinstance(exc, DockerException) else ErrorCategory.HARNESS


RATE_LIMIT_BACKOFF_S = (30.0, 120.0, 600.0)
# Throttling is worth waiting out indefinitely; an upstream 5xx is not. A model
# slower than the provider's gateway fails the same way every time, and each
# attempt cost ~5 minutes and real credits when measured on NIM.
PROVIDER_ERROR_MAX_ATTEMPTS = 2
# How long a budget-exhausted run may go without a model call before the worker
# ends it. Comfortably longer than the slowest observed single call (~302s is a
# gateway timeout, but a live call has run to ~65s) so a slow model is never
# mistaken for a stalled one.
BUDGET_STALL_GRACE_S = 90.0
# A sealed agent cannot reach host.docker.internal — an `internal: true`
# network has no route to the host gateway either. It reaches the proxy through
# a per-run relay that straddles both networks; see SandboxManager.seal().


def transition(run: BenchmarkRun, new_state: RunState) -> None:
    current = RunState(run.state)
    if new_state not in VALID_TRANSITIONS[current]:
        raise ValueError(f"invalid transition {current} -> {new_state}")
    run.state = new_state


def repo_root(repo: Repository) -> Path:
    """On-disk root for a registered repository (clones on first use)."""
    if repo.source == "local":
        return service.register_local(repo.path_or_url)
    return service.clone_github(repo.path_or_url, repo.id)


def materialize_workspace(
    task: BenchmarkTask, repo: Repository | None, config: dict[str, Any], dest: Path
) -> None:
    """Build the agent-visible tree at `dest`, which must not already exist.

    For a task with a base commit this is the leakage boundary (spec §9):
    `git archive` at the BASE commit into a fresh directory with brand-new git
    history, so the solution commit, the original remotes, and future history
    never enter the sandbox. Falling back to a raw directory copy is only for
    fixture-driven demos, which have no history to leak.
    """
    if task.base_commit:
        if repo is None:
            raise RuntimeError(f"task {task.id} has a base commit but no repository")
        service.create_snapshot(repo_root(repo), task.base_commit, dest)
        return
    fixture = config.get("fixture_path")
    if fixture:
        shutil.copytree(fixture, dest)
        return
    raise RuntimeError(
        f"task {task.id} has neither a base commit nor a fixture_path — "
        "nothing to build a workspace from"
    )


class QueueWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        proxy_base_url: str,
        poll_interval: float = 0.2,
        concurrency: int | None = None,
        sandbox_manager: Any | None = None,
    ) -> None:
        self._sessions = session_factory
        self._proxy_base_url = proxy_base_url
        self._poll_interval = poll_interval
        self._semaphore = asyncio.Semaphore(concurrency or settings.queue_concurrency)
        self._sandboxes = sandbox_manager
        self._task: asyncio.Task[None] | None = None
        self._active: dict[str, asyncio.Task[None]] = {}
        self._stopping = asyncio.Event()
        self._paused_experiments: set[str] = set()
        self.paused = False

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("queue worker already started in this process")
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="queue-worker")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            await self._task
            self._task = None
        for task in list(self._active.values()):
            task.cancel()

    def pause_experiment(self, experiment_id: str) -> None:
        self._paused_experiments.add(experiment_id)

    def resume_experiment(self, experiment_id: str) -> None:
        self._paused_experiments.discard(experiment_id)

    async def cancel_run(self, run_id: str) -> bool:
        """Cancel a queued or active run. Active: kill container + task."""
        if self._sandboxes is not None:
            await self._sandboxes.kill(run_id)
        task = self._active.get(run_id)
        if task is not None:
            task.cancel()
        with self._sessions() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is None:
                return False
            state = RunState(run.state)
            if RunState.CANCELLED not in VALID_TRANSITIONS[state]:
                return False
            run.state = RunState.CANCELLED
            run.error_category = ErrorCategory.CANCELLED
            run.completed_at = datetime.now(UTC)
            self._event(session, run_id, "cancelled", {})
            session.commit()
        return True

    @staticmethod
    def retry_run(session: Session, run_id: str) -> bool:
        run = session.get(BenchmarkRun, run_id)
        if run is None or RunState.PENDING not in VALID_TRANSITIONS[RunState(run.state)]:
            return False
        run.state = RunState.PENDING
        run.error_category = None
        run.error_message = None
        session.commit()
        return True

    async def _loop(self) -> None:
        log.info("queue worker started", extra={"event_type": "worker_start"})
        while not self._stopping.is_set():
            await self._end_stalled_budget_runs()
            claimed = None if self.paused else self._claim_next()
            if claimed is None:
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self._poll_interval)
                except TimeoutError:
                    pass
                continue
            task = asyncio.create_task(self._run_guarded(claimed))
            self._active[claimed] = task

            def _done(_t: asyncio.Task[None], rid: str = claimed) -> None:
                self._active.pop(rid, None)

            task.add_done_callback(_done)
        for task in list(self._active.values()):
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _stalled_budget_runs(self, now: datetime) -> list[str]:
        """RUNNING runs whose budget is spent and whose model calls stopped.

        Pure query so it can be tested without a worker or containers.
        """
        from app.api.proxy import run_usage

        stalled: list[str] = []
        with self._sessions() as session:
            running = session.scalars(
                select(BenchmarkRun).where(BenchmarkRun.state == RunState.RUNNING)
            ).all()
            for run in running:
                usage = run_usage(run.id)
                if not usage.get("budget_exhausted"):
                    continue
                last = session.scalar(
                    select(func.max(ModelRequestMetric.created_at)).where(
                        ModelRequestMetric.run_id == run.id
                    )
                )
                reference = last or run.started_at
                if reference is None:
                    continue
                # A slow model is still a live run: only silence counts.
                if (now - reference).total_seconds() >= BUDGET_STALL_GRACE_S:
                    stalled.append(run.id)
        return stalled

    async def _end_stalled_budget_runs(self) -> None:
        """Backstop for a harness that retries a terminal 429.

        Step 1 makes budget exhaustion explicit on the wire, but that relies on
        every harness cooperating — one did not, and held a container for the
        full 1800s timeout after spending its budget in 45 seconds. A run ended
        here is FAILED(budget_exceeded), never TIMED_OUT: it stopped because it
        ran out of allowance, and scoring that as slowness would be wrong.
        """
        for run_id in self._stalled_budget_runs(datetime.now(UTC).replace(tzinfo=None)):
            log.warning(
                "ending run whose budget is spent and whose model calls stopped",
                extra={"run_id": run_id, "event_type": "budget_stall"},
            )
            await self._end_budget_run(run_id)

    async def _end_budget_run(self, run_id: str) -> None:
        """End a spent-budget run WITHOUT throwing away what it achieved.

        The first version killed the container and marked the run FAILED with an
        empty result. A real run then lost 8 successful model calls of work: no
        patch, no usage, no score — indistinguishable from an agent that did
        nothing. At a 40-request budget that is half an hour of the user's
        credits discarded.

        So the patch is extracted while the container is still alive, graded
        exactly as a normal run would be, and the outcome recorded. Running out
        of budget with a working patch is a COMPLETED run, not a failure.
        """
        with self._sessions() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is None or RunState(run.state) is not RunState.RUNNING:
                return
            combo = session.get(ExperimentCombination, run.combination_id)
            experiment = session.get(Experiment, combo.experiment_id) if combo else None
            task_id = combo.task_id if combo else None
            config = dict(experiment.config) if experiment else {}

        # Salvage BEFORE anything is killed: this is the agent's work.
        patch: str | None = None
        if self._sandboxes is not None:
            try:
                extracted = await self._sandboxes.exec(
                    run_id, "git add -A && git diff --cached", timeout_s=120
                )
                patch = extracted.stdout if extracted.exit_code == 0 else None
            except Exception:  # noqa: BLE001 - the container may already be gone
                log.warning("could not extract a patch before ending", extra={"run_id": run_id})

        usage = self._persisted_usage(run_id, run_usage(run_id))
        if task := self._active.get(run_id):
            task.cancel()

        patch_produced = bool(patch and patch.strip())
        if patch_produced:
            self._store_patch(run_id, patch or "")
        evaluation: dict[str, Any] = {"signal": None, "score": None}
        if task_id and patch_produced:
            # Graded on a fresh snapshot, as always — the agent's container is
            # irrelevant to evaluation and is about to be cleaned up anyway.
            try:
                evaluation = await asyncio.to_thread(
                    self._evaluate, run_id, task_id, patch, config
                )
            except Exception:  # noqa: BLE001 - a grading failure must not lose the run
                log.exception("evaluation failed for a budget-ended run",
                              extra={"run_id": run_id})

        with self._sessions() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is None or RunState(run.state) is not RunState.RUNNING:
                return
            transition(run, RunState.EVALUATING)
            if patch_produced:
                transition(run, RunState.COMPLETED)
                run.error_category = ErrorCategory.NONE
                run.error_message = None
            else:
                transition(run, RunState.FAILED)
                run.error_category = ErrorCategory.BUDGET_EXCEEDED
                run.error_message = (
                    "request budget spent before a patch was produced; the harness kept "
                    "retrying a terminal 429 instead of stopping, so the run was ended "
                    "rather than held until its timeout"
                )
            run.completed_at = datetime.now(UTC)
            run.result = {
                "status": "completed" if patch_produced else "failed",
                "patch_produced": patch_produced,
                "final_message": None,
                # The harness never returned, so its own counters are unknown —
                # null, never a fabricated zero. The proxy metrics below are the
                # authoritative record of what was actually spent.
                "input_tokens": None,
                "output_tokens": None,
                "model_requests": None,
                "agent_steps": None,
                "commands_executed": None,
                "evaluation_signal": evaluation.get("signal"),
                "score": evaluation.get("score"),
                "usage": usage,
                "harness_meta": {"ended_by": "budget_watchdog"},
            }
            self._event(session, run_id, "budget_exhausted", {"patch_produced": patch_produced})
            self._settle_experiment(session, run_id)
            session.commit()

    def _claim_next(self) -> str | None:
        self._release_rate_limited()
        with self._sessions() as session:
            pending = session.scalars(
                select(BenchmarkRun)
                .where(BenchmarkRun.state == RunState.PENDING)
                .order_by(BenchmarkRun.created_at)
            ).all()
            for run in pending:
                combo = session.get(ExperimentCombination, run.combination_id)
                if combo is not None and combo.experiment_id in self._paused_experiments:
                    continue
                run_id = run.id
                transition(run, RunState.PREPARING)
                session.commit()
                return run_id
        return None

    async def _run_guarded(self, run_id: str) -> None:
        async with self._semaphore:
            try:
                await self._execute(run_id)
            except asyncio.CancelledError:
                log.info("run cancelled", extra={"run_id": run_id, "event_type": "run_cancelled"})
            except Exception as exc:  # noqa: BLE001 - categorize, never crash the loop
                log.exception("run failed", extra={"run_id": run_id, "event_type": "run_failed"})
                self._fail(run_id, _category_for(exc), str(exc))

    def _settle_experiment(self, session: Session, run_id: str) -> None:
        """Mark an experiment completed once every one of its runs is terminal.

        Status was set to "running" at creation and never updated, so finished
        experiments showed as running forever in the UI.
        """
        run = session.get(BenchmarkRun, run_id)
        if run is None:
            return
        combo = session.get(ExperimentCombination, run.combination_id)
        if combo is None:
            return
        experiment = session.get(Experiment, combo.experiment_id)
        if experiment is None or experiment.status in ("cancelled", "paused"):
            return
        sibling_combos = session.scalars(
            select(ExperimentCombination.id).where(
                ExperimentCombination.experiment_id == combo.experiment_id
            )
        ).all()
        states = session.scalars(
            select(BenchmarkRun.state).where(
                BenchmarkRun.combination_id.in_(list(sibling_combos))
            )
        ).all()
        if states and all(RunState(s) in TERMINAL_STATES for s in states):
            experiment.status = "completed"

    def _fail(self, run_id: str, category: ErrorCategory, message: str) -> None:
        with self._sessions() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is None or RunState(run.state) in (RunState.CANCELLED, RunState.COMPLETED):
                return
            run.state = RunState.FAILED
            run.error_category = category
            run.error_message = message[:2000]
            run.completed_at = datetime.now(UTC)
            self._settle_experiment(session, run_id)
            session.commit()

    async def _execute(self, run_id: str) -> None:
        with self._sessions() as session:
            run = session.get(BenchmarkRun, run_id)
            assert run is not None
            combo = session.get(ExperimentCombination, run.combination_id)
            assert combo is not None
            task = session.get(BenchmarkTask, combo.task_id)
            experiment = session.get(Experiment, combo.experiment_id)
            assert task is not None and experiment is not None
            harness_name, model_id, provider = combo.harness, combo.model_id, combo.provider
            prompt, task_id = task.prompt, task.id
            config = dict(experiment.config)
            repo = session.get(Repository, task.repository_id)
            self._event(session, run_id, "preparing", {})
            session.commit()

        sandboxed = harness_name in SANDBOXED_HARNESSES and self._sandboxes is not None
        # mkdtemp gives us a parent to clean up; the workspace itself must not
        # exist yet because create_snapshot refuses to write into a live dir.
        tmp_root = Path(tempfile.mkdtemp(prefix=f"aso-{run_id[:8]}-"))
        workspace = tmp_root / "workspace"
        try:
            materialize_workspace(task, repo, config, workspace)

            in_price, out_price = self._model_prices(model_id)
            token = issue_run_token(
                run_id,
                model_id,
                max_requests=int(
                    config.get("max_model_requests", DEFAULT_MAX_MODEL_REQUESTS)
                ),
                max_cost_usd=config.get("max_cost_usd"),
                # Without prices the proxy accrues 0.0 forever and the spend
                # ceiling can never fire. Free models make this $0.00, but
                # spec §14 wants cost recorded even when it is zero.
                input_price=in_price,
                output_price=out_price,
                # Route by the combination's own provider so a `fake` cell stays
                # on the fake provider even when a real key is configured.
                provider=provider,
            )
            proxy_base = self._proxy_base_url
            if sandboxed:
                assert self._sandboxes is not None
                # Start the agent from an image that already has the repo's
                # dependencies, so its PREP install is a no-op instead of
                # minutes repeated for every run in the matrix.
                image = await asyncio.to_thread(
                    self._prepared_image, workspace, config, task.repository_id
                )
                await self._sandboxes.create(run_id, workspace, image=image)
                await self._sandboxes.seal(run_id)
                relay = self._sandboxes.relay_host(run_id)
                proxy_base = f"http://{relay}:{settings.backend_port}/proxy"

            harness = get_harness(harness_name)
            request = HarnessRunRequest(
                task_id=task_id,
                task_prompt=prompt,
                workspace_path=workspace,
                model_id=model_id,
                provider=provider,
                timeout_seconds=int(config.get("timeout_seconds", 1800)),
                max_steps=int(config.get("max_steps", 50)),
                temperature=float(config.get("temperature", 0.0)),
                metadata={"run_id": run_id},
                proxy_base_url=proxy_base,
                run_token=token,
            )
            await harness.prepare(request)

            with self._sessions() as session:
                run = session.get(BenchmarkRun, run_id)
                assert run is not None
                transition(run, RunState.RUNNING)
                run.started_at = datetime.now(UTC)
                run.heartbeat_at = run.started_at
                self._event(session, run_id, "running", {"harness": harness_name})
                session.commit()

            result = await harness.run(request)
            usage = self._persisted_usage(run_id, run_usage(run_id))

            # Provider throttling is not a harness bug. Park the run and let it
            # come back rather than burning it as FAILED (spec §30 criterion 24)
            # — at ~50 free requests/day this is the ordinary path, and a
            # spurious FAILED row would corrupt the reliability statistics.
            if usage.get("rate_limited") and result.status != "completed":
                self._rate_limit(run_id, usage)
                return

            # Neither is an upstream 5xx. Measured: z-ai/glm-5.2 on NIM returned
            # 504 after 302s because the provider's own gateway gave up while
            # the model was still generating — nothing the harness did. Parked
            # here, while the run is still RUNNING, because RATE_LIMITED is not
            # reachable from EVALUATING.
            provider_error_exhausted = False
            if (
                usage.get("provider_error")
                and result.status != "completed"
                and not (usage.get("succeeded") or 0)
            ):
                detail = usage.get("provider_error_detail") or "upstream error"
                # A 404 ("not enabled for this account") is final. Parking it
                # would rebuild a container twice to be told the same thing.
                retryable = usage.get("provider_error_retryable") is not False
                if retryable and self._park_for_retry(
                    run_id,
                    usage,
                    event_type="provider_error",
                    category=ErrorCategory.MODEL_PROVIDER,
                    message=f"provider failed ({detail}); queued for retry",
                    max_attempts=PROVIDER_ERROR_MAX_ATTEMPTS,
                ):
                    return
                provider_error_exhausted = True

            with self._sessions() as session:
                run = session.get(BenchmarkRun, run_id)
                assert run is not None
                transition(run, RunState.EVALUATING)
                self._event(session, run_id, "evaluating", {})
                session.commit()

            patch_produced = bool(result.patch and result.patch.strip())
            if patch_produced:
                self._store_patch(run_id, result.patch or "")
            evaluation = await asyncio.to_thread(
                self._evaluate, run_id, task_id, result.patch, config
            )

            with self._sessions() as session:
                run = session.get(BenchmarkRun, run_id)
                assert run is not None
                if result.status == "completed" and self._did_no_work(result, usage):
                    # A harness can exit 0 having achieved nothing: one run
                    # reported completed with 10 upstream requests, ALL failed,
                    # zero agent steps and no patch. Recording that as success
                    # would count a run that never ran as a working combination
                    # and corrupt the reliability statistics it feeds.
                    transition(run, RunState.FAILED)
                    run.error_category = ErrorCategory.HARNESS
                    run.error_message = (
                        "harness reported success but did no work: "
                        f"{usage.get('succeeded')} of {usage.get('requests')} upstream "
                        f"requests returned 200, {result.agent_steps} agent steps, no patch. "
                        + (result.error_message or "")[:800]
                    )
                elif result.status == "completed":
                    transition(run, RunState.COMPLETED)
                    run.error_category = ErrorCategory.NONE
                elif result.status == "timeout":
                    transition(run, RunState.TIMED_OUT)
                    run.error_category = ErrorCategory.TIMEOUT
                elif provider_error_exhausted:
                    # Retried to the cap and still failing: report the provider,
                    # not the harness, so the result reads as "this model is
                    # unusable on this provider" rather than "something broke".
                    transition(run, RunState.FAILED)
                    run.error_category = ErrorCategory.MODEL_PROVIDER
                    detail = usage.get("provider_error_detail") or "upstream error"
                    run.error_message = (
                        # Say which it was: a permanent rejection was never
                        # retried, and claiming otherwise misreports the cost.
                        f"provider rejected this model permanently ({detail}) — "
                        "it is not usable on this account or provider. "
                        if usage.get("provider_error_retryable") is False
                        else (
                            f"provider failed on every attempt ({detail}) after "
                            f"{PROVIDER_ERROR_MAX_ATTEMPTS} retries — the model likely "
                            "exceeds the provider's own gateway timeout. "
                        )
                    ) + (result.error_message or "")[:800]
                elif self._looks_like_provider_timeout(result, usage):
                    # Every request succeeded upstream, yet the harness reported
                    # a generation failure: the provider was slower than the
                    # client would wait. That is a timeout, not a broken
                    # harness, and execution efficiency is 15% of the score —
                    # slowness should read as a measurement, not a crash.
                    transition(run, RunState.TIMED_OUT)
                    run.error_category = ErrorCategory.TIMEOUT
                    run.error_message = (
                        "provider responded but slower than the client would wait; "
                        f"{usage.get('succeeded')} of {usage.get('requests')} "
                        "upstream requests returned 200. "
                        + (result.error_message or "")[:1200]
                    )
                else:
                    transition(run, RunState.FAILED)
                    run.error_category = ErrorCategory.HARNESS
                    run.error_message = (result.error_message or "")[:2000]
                run.completed_at = datetime.now(UTC)
                run.result = {
                    "status": result.status,
                    "patch_produced": patch_produced,
                    "final_message": result.final_message,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "model_requests": result.model_requests,
                    "agent_steps": result.agent_steps,
                    "commands_executed": result.commands_executed,
                    "evaluation_signal": evaluation.get("signal"),
                    "score": evaluation.get("score"),
                    # Quota burn must be visible before it runs out, not after.
                    "usage": usage,
                    # Harness telemetry (spec §14). Without it a run that exits
                    # 0 having done nothing looks identical to a good one.
                    "harness_meta": result.raw_metadata,
                }
                self._event(session, run_id, result.status, {"patch_produced": patch_produced})
                self._settle_experiment(session, run_id)
                session.commit()
        finally:
            revoke_run_token(run_id)
            if sandboxed and self._sandboxes is not None:
                await self._sandboxes.cleanup(run_id)
            shutil.rmtree(tmp_root, ignore_errors=True)

    def _evaluate(
        self, run_id: str, task_id: str, patch: str | None, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Grade the patch on a fresh snapshot (Tension 2) and persist results.

        The snapshot is rebuilt here rather than reusing the agent's workspace:
        grading must never see anything the agent did except the patch itself.
        """
        from sqlalchemy import select as sa_select

        from app.evaluators.engine import EvaluationContext
        from app.models import EvaluationResult
        from app.sandboxes.runner import evaluate_in_sandbox

        with self._sessions() as session:
            task = session.get(BenchmarkTask, task_id)
            if task is None:
                return {"signal": "no_evaluation_configured", "score": None}
            repo = session.get(Repository, task.repository_id)
            hidden = {
                c.relpath: c.content
                for c in session.scalars(
                    sa_select(HiddenTestCandidate).where(
                        HiddenTestCandidate.task_id == task_id,
                        HiddenTestCandidate.approved.is_(True),
                    )
                )
            }

        if not task.base_commit and not config.get("fixture_path"):
            return {"signal": "no_evaluation_configured", "score": None}

        with tempfile.TemporaryDirectory(prefix=f"aso-eval-{run_id[:8]}-") as tmp:
            tmp_path = Path(tmp)
            snapshot_source = tmp_path / "base"
            materialize_workspace(task, repo, config, snapshot_source)
            context = EvaluationContext(
                patch=patch,
                snapshot_source=snapshot_source,
                commands=dict(config.get("commands") or {"test": "pytest -v"}),
                test_framework=config.get("test_framework", "pytest"),
                baseline_cases=[tuple(c) for c in config.get("baseline_cases", [])],
                hidden_tests=hidden,
            )
            # Containerised: install and the test runner share one interpreter,
            # and the agent's patch no longer executes on the host.
            outcome = evaluate_in_sandbox(
                context,
                tmp_path,
                repo_id=task.repository_id,
                install_cmd=(config.get("commands") or {}).get("install"),
            )

        with self._sessions() as session:
            session.add(
                EvaluationResult(
                    run_id=run_id,
                    signal=outcome.signal,
                    score=outcome.score,
                    results=outcome.results,
                )
            )
            session.commit()
        return {"signal": outcome.signal, "score": outcome.score}

    def _rate_limit(self, run_id: str, usage: dict[str, Any]) -> None:
        """RUNNING → RATE_LIMITED with a persisted backoff deadline."""
        self._park_for_retry(
            run_id,
            usage,
            event_type="rate_limited",
            category=ErrorCategory.RATE_LIMITED,
            message="provider rate limited; queued for retry",
        )

    def _park_for_retry(
        self,
        run_id: str,
        usage: dict[str, Any],
        event_type: str,
        category: str,
        message: str,
        max_attempts: int | None = None,
    ) -> bool:
        """RUNNING → RATE_LIMITED with a persisted backoff deadline.

        Returns False when the attempt cap is reached, so the caller can fail
        the run terminally instead. Throttling is uncapped — waiting is the
        correct response to a daily quota — but an upstream 5xx can be
        deterministic (a model slower than the provider's own gateway), and
        retrying that forever costs minutes and credits per attempt.
        """
        with self._sessions() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is None or RunState(run.state) is not RunState.RUNNING:
                return True
            attempts = session.scalars(
                select(RunEvent).where(
                    RunEvent.run_id == run_id, RunEvent.event_type == event_type
                )
            ).all()
            if max_attempts is not None and len(attempts) >= max_attempts:
                return False
            delay = RATE_LIMIT_BACKOFF_S[min(len(attempts), len(RATE_LIMIT_BACKOFF_S) - 1)]
            transition(run, RunState.RATE_LIMITED)
            run.error_category = category
            run.error_message = message
            run.retry_after = datetime.now(UTC) + timedelta(seconds=delay)
            run.result = {**(run.result or {}), "usage": usage}
            self._event(session, run_id, event_type, {"retry_in_s": delay, **usage})
            session.commit()
        log.info(
            "run parked for retry",
            extra={"run_id": run_id, "event_type": event_type, "duration": delay},
        )
        return True

    def _release_rate_limited(self) -> None:
        """RATE_LIMITED → PENDING once the backoff has elapsed."""
        now = datetime.now(UTC)
        with self._sessions() as session:
            parked = session.scalars(
                select(BenchmarkRun).where(BenchmarkRun.state == RunState.RATE_LIMITED)
            ).all()
            released = False
            for run in parked:
                deadline = run.retry_after
                # Rows written before this column existed, or by an older
                # process, have no deadline — release rather than strand them.
                if deadline is not None:
                    if deadline.tzinfo is None:
                        deadline = deadline.replace(tzinfo=UTC)
                    if deadline > now:
                        continue
                transition(run, RunState.PENDING)
                run.retry_after = None
                released = True
            if released:
                session.commit()

    @staticmethod
    def _prepared_image(workspace: Path, config: dict[str, Any], repo_id: str) -> str | None:
        """Image with this repo's dependencies baked in, or None for the default."""
        from app.sandboxes.manager import docker_available
        from app.sandboxes.prepared import ensure_prepared_image

        install = (config.get("commands") or {}).get("install")
        if not install or not docker_available():
            return None
        image, _ = ensure_prepared_image(workspace, install, repo_id)
        return image

    @staticmethod
    def _did_no_work(result: Any, usage: dict[str, Any]) -> bool:
        """A 'completed' run that cannot have accomplished anything.

        Deliberately narrow: no upstream request ever returned 200, AND the
        agent took no steps, AND there is no patch. An empty patch is a
        legitimate benchmark result, so a run that genuinely tried and failed
        to solve the task still counts as completed — this only catches the
        case where the model was never reached at all.

        `agent_steps is None` means the harness could not report a count, which
        is not evidence of doing nothing: an unreadable trajectory must not be
        able to condemn a run that actually worked.
        """
        if usage.get("requests") and (usage.get("succeeded") or 0) > 0:
            return False
        if result.patch and result.patch.strip():
            return False
        if result.agent_steps is None:
            return False
        return not result.agent_steps

    @staticmethod
    def _looks_like_provider_timeout(result: Any, usage: dict[str, Any]) -> bool:
        """Harness failed, but every upstream request succeeded.

        The signature of a client giving up on a slow provider: requests were
        made, all returned 200, and the harness still could not get output.
        A genuinely broken harness either makes no requests or sees errors.

        This demands POSITIVE evidence — at least one recorded 200 — rather
        than merely an absence of recorded failures. The earlier version asked
        `failed_requests == 0`, which is trivially true when nothing was
        recorded at all: an unreachable proxy wrote zero metric rows, and the
        run was labelled "provider responded but slower than the client would
        wait; 1 upstream requests all succeeded" when in truth no request had
        reached any provider. Inventing a latency story for a connection
        failure is exactly the kind of fake metric §4 forbids.
        """
        if result.status != "failed":
            return False
        return (usage.get("succeeded") or 0) > 0

    def _persisted_usage(self, run_id: str, live: dict[str, Any]) -> dict[str, Any]:
        """Cumulative usage for a run, from the metric rows.

        `run_usage()` reads the in-memory run token, which is reissued on every
        attempt — so a retried run reported only its LAST attempt while having
        spent every attempt's quota. The metric rows persist across attempts and
        restarts, so they are the honest total. Flags (rate_limited,
        budget_exhausted) still come from the live token: they describe the
        attempt that just ran.
        """
        with self._sessions() as session:
            rows = session.scalars(
                select(ModelRequestMetric).where(ModelRequestMetric.run_id == run_id)
            ).all()
        if not rows:
            # No rows is not "nothing failed" — it is no evidence either way.
            # Say so explicitly so callers cannot read silence as success.
            return {**live, "succeeded": 0, "failed_requests": 0}
        return {
            **live,
            "requests": len(rows),
            "input_tokens": sum(r.input_tokens or 0 for r in rows),
            "output_tokens": sum(r.output_tokens or 0 for r in rows),
            "succeeded": sum(1 for r in rows if r.http_status == 200),
            # Requests that reached the provider but returned no usable
            # response — the shape a client timeout leaves behind.
            "failed_requests": sum(1 for r in rows if r.http_status != 200),
        }

    def _model_prices(self, model_id: str) -> tuple[float, float]:
        """Per-token prices from the pinned snapshot; (0, 0) when unknown."""
        with self._sessions() as session:
            snapshot = session.scalars(
                select(ModelSnapshot)
                .where(ModelSnapshot.model_id == model_id)
                .order_by(ModelSnapshot.created_at.desc())
            ).first()
        if snapshot is None:
            return 0.0, 0.0
        meta = snapshot.meta or {}
        return (
            float(meta.get("input_price_per_token") or 0.0),
            float(meta.get("output_price_per_token") or 0.0),
        )

    def _store_patch(self, run_id: str, patch: str) -> None:
        """Atomic artifact write (tmp+rename) with checksum in DB."""
        artifacts_dir = settings.data_dir.resolve() / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        final = artifacts_dir / f"{run_id}.patch"
        tmp = final.with_suffix(".patch.tmp")
        tmp.write_text(patch)
        tmp.rename(final)
        checksum = hashlib.sha256(patch.encode()).hexdigest()
        with self._sessions() as session:
            session.add(Artifact(run_id=run_id, kind="patch", path=str(final), checksum=checksum))
            session.commit()

    @staticmethod
    def _event(session: Session, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        session.add(RunEvent(run_id=run_id, event_type=event_type, payload=payload))
