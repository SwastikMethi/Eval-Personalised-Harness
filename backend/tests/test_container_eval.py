"""Baseline and evaluation run in a container with deps installed once.

The bug being pinned: running evaluator commands on the host means `pip` and
the test runner resolve independently. On a machine with both miniforge and a
uv-managed Python they land on different interpreters, so install reports
success while installing nothing the tests can see.
"""

import subprocess
from pathlib import Path

import pytest

from app.repositories.baseline import run_baseline
from app.sandboxes.exec import CommandResult
from app.sandboxes.manager import container_kwargs, docker_available
from app.sandboxes.prepared import image_tag, manifest_files, manifest_hash

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


needs_image = pytest.mark.skipif(not _image_present(), reason=f"{IMAGE} not built")


# --- hardening parity (no docker needed beyond the availability gate) --------


def test_agent_and_eval_containers_share_hardening(tmp_path: Path) -> None:
    """Configured separately they would drift, and the weaker one is what counts."""
    kwargs = container_kwargs(tmp_path, "run-1")
    assert kwargs["user"] == "1000"
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges"]
    assert kwargs["pids_limit"] > 0
    assert kwargs["mem_limit"].endswith("m")


# --- prepared image identity ------------------------------------------------


def test_hash_tracks_manifests_not_unrelated_files(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("pandas==2.3.2\n")
    (tmp_path / "README.md").write_text("hello")
    first = manifest_hash(tmp_path, "pip install -r requirements.txt")

    (tmp_path / "README.md").write_text("hello again")
    assert manifest_hash(tmp_path, "pip install -r requirements.txt") == first

    (tmp_path / "requirements.txt").write_text("pandas==2.3.3\n")
    assert manifest_hash(tmp_path, "pip install -r requirements.txt") != first


def test_install_command_is_part_of_image_identity(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("pandas\n")
    a = image_tag("repo", tmp_path, "pip install -r requirements.txt")
    b = image_tag("repo", tmp_path, "pip install -r requirements.txt --no-deps")
    assert a != b, "a different install command builds a different environment"


def test_only_dependency_manifests_are_copied(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("x")
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "app.py").write_text("print('hi')")
    names = {p.name for p in manifest_files(tmp_path)}
    assert names == {"requirements.txt", "package.json"}


# --- the regression ---------------------------------------------------------


@needs_image
def test_install_and_tests_share_one_interpreter(tmp_path: Path) -> None:
    """On the host, pip and pytest can be different Pythons. In the container
    they cannot be — that is the entire point of this change."""
    from app.sandboxes.container_exec import ContainerExecutor

    with ContainerExecutor(tmp_path, image=IMAGE, label="test") as run:
        pip_home = run("python -m pip --version", tmp_path)
        py_home = run("python -c 'import sys; print(sys.prefix)'", tmp_path)

    assert pip_home.exit_code == 0, pip_home.stdout
    assert py_home.exit_code == 0, py_home.stdout
    # `pip --version` prints the interpreter prefix it will install into.
    assert py_home.stdout.strip() in pip_home.stdout


@needs_image
def test_a_dependency_installed_in_the_container_is_importable(tmp_path: Path) -> None:
    from app.sandboxes.container_exec import ContainerExecutor

    with ContainerExecutor(tmp_path, image=IMAGE, label="test") as run:
        installed = run("python -m pip install --quiet six", tmp_path, timeout_s=180)
        imported = run("python -c 'import six; print(six.__version__)'", tmp_path)

    assert installed.exit_code == 0, installed.stdout
    # The exact failure from the bug report: installed, then not importable.
    assert imported.exit_code == 0, f"installed but not importable: {imported.stdout}"


@needs_image
def test_executor_runs_in_the_requested_subdirectory(tmp_path: Path) -> None:
    """The evaluator grades in workdir/graded, not at the mount root."""
    from app.sandboxes.container_exec import ContainerExecutor

    (tmp_path / "graded").mkdir()
    (tmp_path / "graded" / "marker.txt").write_text("here")

    with ContainerExecutor(tmp_path, image=IMAGE, label="test") as run:
        result = run("cat marker.txt", tmp_path / "graded")

    assert result.exit_code == 0, result.stdout
    assert "here" in result.stdout


@needs_image
def test_baseline_through_the_container_executor(tmp_path: Path) -> None:
    from app.sandboxes.container_exec import ContainerExecutor

    (tmp_path / "test_x.py").write_text("def test_ok():\n    assert True\n")
    with ContainerExecutor(tmp_path, image=IMAGE, label="test") as run:
        outcome = run_baseline(
            tmp_path,
            {
                # The base image carries the harnesses, not a test runner — a
                # real repo brings its own, exactly as here. This is the
                # install-then-test path the host version got wrong.
                "install": "python -m pip install --quiet pytest",
                "test": "python -m pytest -q test_x.py",
            },
            "pytest",
            execute=run,
        )
    assert outcome.benchmarkable, outcome.steps
    assert outcome.steps["install"]["exit_code"] == 0
    assert outcome.steps["test"]["exit_code"] == 0, outcome.steps["test"]["stdout"][-500:]


# --- honest degradation -----------------------------------------------------


def test_prebuilt_install_failure_blocks_and_keeps_its_log() -> None:
    """A failed image build is the repo's install failing; it must read as
    that, with the log, not as an opaque build error."""
    build = CommandResult(
        command="pip install -r requirements.txt",
        exit_code=1,
        stdout="ERROR: Could not find a version that satisfies nonexistent-pkg",
        stderr="",
        duration_s=1.0,
    )
    outcome = run_baseline(Path("/tmp"), {"test": "true"}, "pytest", prebuilt_install=build)

    assert outcome.benchmarkable is False
    assert "nonexistent-pkg" in outcome.steps["install"]["stdout"]
    assert "test" not in outcome.steps, "must not run tests after install failed"


def test_prebuilt_install_success_is_not_run_twice() -> None:
    """Deps came from the image; re-running install would waste the saving."""
    calls: list[str] = []

    def spy(command: str, cwd: Path, **_: object) -> CommandResult:
        calls.append(command)
        return CommandResult(command, 0, "", "", 0.1)

    build = CommandResult("pip install -r requirements.txt", 0, "ok", "", 5.0)
    run_baseline(
        Path("/tmp"),
        {"install": "pip install -r requirements.txt", "test": "true"},
        "pytest",
        execute=spy,
        prebuilt_install=build,
    )
    assert "pip install -r requirements.txt" not in calls
    assert "true" in calls
