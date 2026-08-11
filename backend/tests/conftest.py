import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Isolated database per test session, set before app imports.
_tmp = tempfile.mkdtemp(prefix="aso-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ["DATA_DIR"] = _tmp


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    """Migrate the test database once, up front.

    Schema used to appear only as a side effect of some test calling
    create_app(), so a module that touched the DB directly passed or failed
    depending on collection order. Running migrations here also means the
    suite exercises the real migration path rather than a parallel create_all.
    """
    from app.db.engine import ensure_schema

    ensure_schema()
    yield
