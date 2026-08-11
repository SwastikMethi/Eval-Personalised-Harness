"""Alembic environment.

The URL comes from `app.core.config.settings`, never from alembic.ini, so the
migration target always matches what the application itself opens — including
the DATABASE_URL override the test suite sets in conftest.

`render_as_batch=True` is required for SQLite: it has no real ALTER TABLE, so
Alembic emits copy-and-rename batches instead.
"""

from logging.config import fileConfig

from alembic import context

from app.core.config import settings
from app.db.engine import make_engine
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Reuse the application's engine factory so migrations get the same WAL
    # pragmas and data-directory creation the app itself relies on.
    connectable = make_engine()
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
