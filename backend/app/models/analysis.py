"""Stage-2 entities: analysis, editable commands, baseline results."""

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdTimestampMixin


class RepositoryAnalysis(Base, IdTimestampMixin):
    __tablename__ = "repository_analyses"

    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"))
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    package_managers: Mapped[list[str]] = mapped_column(JSON, default=list)
    dependency_files: Mapped[list[str]] = mapped_column(JSON, default=list)
    test_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    ci_workflows: Mapped[list[str]] = mapped_column(JSON, default=list)
    runtime_versions: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    supported: Mapped[bool] = mapped_column(Boolean, default=False)
    size_bytes: Mapped[int] = mapped_column(default=0)


class RepositoryCommand(Base, IdTimestampMixin):
    __tablename__ = "repository_commands"

    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), unique=True)
    install: Mapped[str | None] = mapped_column(String(500), default=None)
    build: Mapped[str | None] = mapped_column(String(500), default=None)
    test: Mapped[str | None] = mapped_column(String(500), default=None)
    lint: Mapped[str | None] = mapped_column(String(500), default=None)
    typecheck: Mapped[str | None] = mapped_column(String(500), default=None)
    test_framework: Mapped[str | None] = mapped_column(String(40), default=None)
    user_edited: Mapped[bool] = mapped_column(Boolean, default=False)


class BaselineResult(Base, IdTimestampMixin):
    __tablename__ = "baseline_results"

    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"))
    base_commit: Mapped[str] = mapped_column(String(64))
    benchmarkable: Mapped[bool] = mapped_column(Boolean, default=False)
    warn: Mapped[bool] = mapped_column(Boolean, default=False)
    steps: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    test_cases: Mapped[list[Any]] = mapped_column(JSON, default=list)
