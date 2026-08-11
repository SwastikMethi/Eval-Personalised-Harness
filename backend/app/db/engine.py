"""SQLite engine with WAL mode + busy_timeout (eng review 7A).

One permanent background writer (queue worker) plus API/SSE readers share
this file; WAL prevents writer-blocks-readers, busy_timeout absorbs the rest.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(database_url: str | None = None) -> Engine:
    url = database_url or settings.database_url
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(eng, "connect", _configure_sqlite)
    return eng


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def ensure_schema() -> None:
    """Bring the database up to head.

    Migrations are the single source of truth for schema — there is no
    `create_all` anywhere. This is a local single-user app, so upgrading on
    startup keeps `make dev`, `make demo`, and the test suite working without
    a separate manual step; `make migrate` does the same thing explicitly.
    """
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    command.upgrade(cfg, "head")


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
