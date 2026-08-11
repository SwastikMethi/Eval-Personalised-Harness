"""Migrations are the single source of truth for schema (spec §5, §18).

The drift test is the guard that makes that true: if someone edits a model
without generating a migration, autogenerate would produce a non-empty diff
and this fails. Without it, models and migrations silently diverge and the
next fresh install gets a different schema than the one under test.
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db.engine import engine, ensure_schema
from app.models import Base


def test_upgrade_head_creates_every_table() -> None:
    ensure_schema()
    from sqlalchemy import inspect

    tables = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables) <= tables
    assert "alembic_version" in tables


def test_no_migration_drift() -> None:
    ensure_schema()
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"render_as_batch": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == [], (
        "models have drifted from migrations — run:\n"
        "  cd backend && uv run alembic revision --autogenerate -m '<what changed>'\n"
        f"diff: {diff}"
    )
