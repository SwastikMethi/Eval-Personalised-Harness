"""Stage-1 skeleton entities (migrations grow per stage — eng review Tension 4).

Run state machine (spec §13):

  PENDING → PREPARING → RUNNING → EVALUATING → COMPLETED
     │          │           │          │
     └──────────┴───────────┴──────────┴──→ FAILED / CANCELLED / TIMED_OUT / RATE_LIMITED
  (reconciliation sweep: stale PREPARING/RUNNING → FAILED(crash), retryable)
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdTimestampMixin


class RunState(StrEnum):
    PENDING = "PENDING"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    EVALUATING = "EVALUATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    RATE_LIMITED = "RATE_LIMITED"


TERMINAL_STATES = {
    RunState.COMPLETED,
    RunState.FAILED,
    RunState.CANCELLED,
    RunState.TIMED_OUT,
}

VALID_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.PENDING: {RunState.PREPARING, RunState.CANCELLED},
    RunState.PREPARING: {RunState.RUNNING, RunState.FAILED, RunState.CANCELLED},
    RunState.RUNNING: {
        RunState.EVALUATING,
        RunState.FAILED,
        RunState.CANCELLED,
        RunState.TIMED_OUT,
        RunState.RATE_LIMITED,
    },
    RunState.RATE_LIMITED: {RunState.PENDING, RunState.FAILED, RunState.CANCELLED},
    RunState.EVALUATING: {RunState.COMPLETED, RunState.FAILED},
    RunState.COMPLETED: set(),
    RunState.FAILED: {RunState.PENDING},  # retry
    RunState.CANCELLED: set(),
    RunState.TIMED_OUT: {RunState.PENDING},  # retry
}


class Repository(Base, IdTimestampMixin):
    __tablename__ = "repositories"

    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20))  # local | github
    path_or_url: Mapped[str] = mapped_column(String(1000))
    default_branch: Mapped[str | None] = mapped_column(String(200), default=None)
    current_commit: Mapped[str | None] = mapped_column(String(64), default=None)


class BenchmarkTask(Base, IdTimestampMixin):
    __tablename__ = "benchmark_tasks"

    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"))
    kind: Mapped[str] = mapped_column(String(20))  # user_defined | commit | pr
    title: Mapped[str] = mapped_column(String(500))
    prompt: Mapped[str] = mapped_column(String)
    base_commit: Mapped[str | None] = mapped_column(String(64), default=None)


class Experiment(Base, IdTimestampMixin):
    __tablename__ = "experiments"

    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    repetitions: Mapped[int] = mapped_column(default=3)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ExperimentCombination(Base, IdTimestampMixin):
    __tablename__ = "experiment_combinations"

    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"))
    task_id: Mapped[str] = mapped_column(ForeignKey("benchmark_tasks.id"))
    harness: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(100))
    model_id: Mapped[str] = mapped_column(String(200))


class BenchmarkRun(Base, IdTimestampMixin):
    __tablename__ = "benchmark_runs"

    combination_id: Mapped[str] = mapped_column(ForeignKey("experiment_combinations.id"))
    repetition: Mapped[int] = mapped_column(default=1)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    state: Mapped[str] = mapped_column(String(20), default=RunState.PENDING)
    error_category: Mapped[str | None] = mapped_column(String(40), default=None)
    error_message: Mapped[str | None] = mapped_column(String, default=None)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(default=None)
    # When a RATE_LIMITED run may return to PENDING. Persisted rather than held
    # in the worker so a backoff survives a restart (spec §13: recover queued
    # experiment state) — at ~50 free requests/day this is the normal path.
    retry_after: Mapped[datetime | None] = mapped_column(default=None)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RunEvent(Base, IdTimestampMixin):
    __tablename__ = "run_events"

    run_id: Mapped[str] = mapped_column(ForeignKey("benchmark_runs.id"))
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Artifact(Base, IdTimestampMixin):
    __tablename__ = "artifacts"

    run_id: Mapped[str] = mapped_column(ForeignKey("benchmark_runs.id"))
    kind: Mapped[str] = mapped_column(String(40))  # log | patch | output
    path: Mapped[str] = mapped_column(String(1000))
    checksum: Mapped[str] = mapped_column(String(64))
