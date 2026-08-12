"""Why the detector emits `python -m pytest` rather than `pytest`.

Executable proof rather than a comment. A src-layout repo with no pytest
config — package `src/` with __init__.py, `tests/` without one — cannot import
its own package under bare `pytest`, because pytest puts the first parent
directory without __init__.py (here `tests/`) on sys.path and the repo root
never gets there.

This is the Pokemon-Battle-Simulator shape, and the second of the two bugs
behind its `TEST exit 2`. The first was install and tests running under
different interpreters, fixed by running in a container at all.
"""

import subprocess
from pathlib import Path

import pytest

from app.sandboxes.manager import docker_available

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not docker_available(), reason="docker unavailable"),
]

IMAGE = "aso-sandbox-python:dev"


def _image_present() -> bool:
    return (
        subprocess.run(
            ["docker", "image", "inspect", IMAGE], capture_output=True, timeout=60
        ).returncode
        == 0
    )


pytestmark = [
    *pytestmark,
    pytest.mark.skipif(not _image_present(), reason=f"{IMAGE} not built"),
]


def _src_layout_repo(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("")
    (root / "src" / "thing.py").write_text("VALUE = 41\n")
    (root / "tests").mkdir()  # no __init__.py, exactly like the real repo
    (root / "tests" / "test_thing.py").write_text(
        "from src.thing import VALUE\n\ndef test_v():\n    assert VALUE + 1 == 42\n"
    )


def test_without_cwd_on_syspath_the_package_cannot_be_imported(tmp_path: Path) -> None:
    """`python -P -m pytest` isolates the one variable that matters.

    `-P` tells Python not to put the current directory on sys.path, which is
    exactly the situation the bare `pytest` console script creates. Testing it
    this way avoids depending on where a console script lands or whether the
    directory it lands in is executable, and demonstrates the mechanism itself.
    """
    from app.sandboxes.container_exec import ContainerExecutor

    _src_layout_repo(tmp_path)
    with ContainerExecutor(tmp_path, image=IMAGE, label="test") as run:
        run("python -m pip install --quiet pytest", tmp_path, timeout_s=180)
        result = run("python -P -m pytest -v", tmp_path)

    assert result.exit_code != 0, f"expected a collection error, got:\n{result.stdout[-800:]}"
    # The exact error the user saw.
    assert "No module named 'src'" in result.stdout, result.stdout[-800:]


def test_module_form_collects_and_passes(tmp_path: Path) -> None:
    from app.sandboxes.container_exec import ContainerExecutor

    _src_layout_repo(tmp_path)
    with ContainerExecutor(tmp_path, image=IMAGE, label="test") as run:
        run("python -m pip install --quiet pytest", tmp_path, timeout_s=180)
        # As uid 1000 the console script lands in $HOME/.local/bin, which is not
        # on PATH. Put it there so `pytest` resolves exactly as it did on the
        # machine that reported this — otherwise we would be testing "command
        # not found" instead of the sys.path behaviour.
        result = run("python -m pytest -v", tmp_path)

    assert result.exit_code == 0, result.stdout[-800:]
    assert "1 passed" in result.stdout
