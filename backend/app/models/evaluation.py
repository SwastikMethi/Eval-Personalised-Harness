"""Stage-5 entities: hidden-test candidates + evaluation results."""

from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdTimestampMixin


class HiddenTestCandidate(Base, IdTimestampMixin):
    __tablename__ = "hidden_test_candidates"

    task_id: Mapped[str] = mapped_column(ForeignKey("benchmark_tasks.id"))
    relpath: Mapped[str] = mapped_column(String(1000))
    content: Mapped[str] = mapped_column(String)
    change_type: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[str] = mapped_column(String(10))
    reject_reason: Mapped[str | None] = mapped_column(String(500), default=None)
    approved: Mapped[bool | None] = mapped_column(Boolean, default=None)  # None = undecided


class EvaluationResult(Base, IdTimestampMixin):
    __tablename__ = "evaluation_results"

    run_id: Mapped[str] = mapped_column(ForeignKey("benchmark_runs.id"))
    # Which task this score is for. Null on rows written before a run could
    # cover more than one, and on commit runs where the combination's single
    # task is unambiguous.
    #
    # Load-bearing for grouped runs: without it two answers from one run
    # collapse into a single score, and the per-task efficiency normalisation
    # in scoring/aggregate.py attributes both to the group's first task.
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("benchmark_tasks.id"), default=None
    )
    signal: Mapped[str] = mapped_column(String(40), default="ok")
    score: Mapped[float | None] = mapped_column(Float, default=None)
    results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
