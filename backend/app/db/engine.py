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


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
