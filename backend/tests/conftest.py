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
