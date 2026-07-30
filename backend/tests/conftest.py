import os
import tempfile
from pathlib import Path

# Isolated database per test session, set before app imports.
_tmp = tempfile.mkdtemp(prefix="aso-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ["DATA_DIR"] = _tmp
