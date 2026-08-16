import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Isolated database per test session, set before app imports.
_tmp = tempfile.mkdtemp(prefix="aso-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ["DATA_DIR"] = _tmp

# The suite must never reach a real provider. Settings read the repo-root
# .env, so without this the app would install a live provider and the tests
# would spend real quota — of which the free tier grants ~50 a DAY. An
# explicit empty env var wins over the .env file and keeps us on
# FakeProvider, which is what every test and `make demo` assume.
#
# One line per provider key, and it must be UNCONDITIONAL: these normally
# live in .env and never reach os.environ, so anything that only rewrites
# keys already present is a no-op. Adding NVIDIA_API_KEY without adding it
# here made NIM the installed default and the proxy tests started calling
# the network (502s, 20s+ runs). test_provider_isolation.py fails loudly if
# a future provider is missed.
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["NVIDIA_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""


# The REAL database, not the throwaway one this suite runs against: the test
# DATABASE_URL above points at a temp file that can never contain a live run.
LIVE_DB = Path(__file__).resolve().parents[2] / "data" / "aso.db"
LIVE_STATES = ("PENDING", "PREPARING", "RUNNING", "EVALUATING")


def active_run(db_path: Path) -> tuple[str, str] | None:
    """(id, state) of a benchmark run in flight, or None.

    Opened read-only and never created: a missing database means there is no
    backend to disturb. Any read problem returns None rather than blocking the
    suite — this guard protects a run, it must not become a way to fail CI.
    """
    import sqlite3

    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        try:
            placeholders = ",".join("?" * len(LIVE_STATES))
            row = conn.execute(
                f"SELECT id, state FROM benchmark_runs WHERE state IN ({placeholders}) LIMIT 1",
                LIVE_STATES,
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return (row[0], row[1]) if row else None


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


@pytest.fixture(autouse=True)
def _never_disturb_a_live_run(request: pytest.FixtureRequest) -> None:
    """Skip container-creating tests while a benchmark run is in flight.

    Twice now this suite has destroyed a user's run: it churns enough Docker
    containers to put the daemon under pressure, and the kernel kills whatever
    it likes — including the live run's agent and relay, which then reports a
    sandbox failure that had nothing to do with the model or the repo.

    The `docker` marker exists so those tests can be deselected, and relying on
    whoever types the command to remember is what failed. This makes it
    automatic: the protection holds no matter how pytest is invoked.
    """
    if request.node.get_closest_marker("docker") is None:
        return

    if (active := active_run(LIVE_DB)) is not None:
        pytest.skip(
            f"a benchmark run is active ({active[0][:12]}, {active[1]}); container tests "
            "put Docker under pressure and have killed live runs twice"
        )


@pytest.fixture(autouse=True)
def _isolate_provider_registry() -> Iterator[None]:
    """Undo provider registration after every test.

    set_provider/register_provider mutate module globals, so a test that
    registers one changes which provider every LATER test routes to — and
    tests that pass alone fail in a suite, differently each run under random
    ordering. Restoring here fixes the class rather than one offender.
    """
    from app.api import proxy

    default, named = proxy._provider, dict(proxy._named_providers)
    yield
    proxy._provider = default
    proxy._named_providers.clear()
    proxy._named_providers.update(named)
