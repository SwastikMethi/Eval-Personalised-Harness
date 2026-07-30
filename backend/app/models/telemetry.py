"""Stage-3 entities: pinned model snapshots + per-request metrics."""

from typing import Any

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdTimestampMixin


class ModelSnapshot(Base, IdTimestampMixin):
    __tablename__ = "model_snapshots"

    provider: Mapped[str] = mapped_column(String(100))
    model_id: Mapped[str] = mapped_column(String(200))
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ModelRequestMetric(Base, IdTimestampMixin):
    __tablename__ = "model_request_metrics"

    # Plain string (no FK): telemetry rows are written on the proxy hot path
    # and must never fail a request over run-row lifecycle timing.
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    model_id: Mapped[str] = mapped_column(String(200))
    latency_ms: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int | None] = mapped_column(default=None)
    output_tokens: Mapped[int | None] = mapped_column(default=None)
    is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    http_status: Mapped[int] = mapped_column(default=200)
    raw_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
