"""The sandbox image has to be able to run the repo's own install command.

`Eval-Personalised-Harness` failed its baseline with `make: not found`, and the
build log said `transferring context: 138B` — the generated Dockerfile and
nothing else. Three defects stacked:

  1. `make` was absent from the sandbox image;
  2. `Makefile` was not a recognised manifest, so it was never copied;
  3. manifests were discovered root-only and copied FLATTENED to their
     basename, so a repo keeping `backend/pyproject.toml` contributed nothing
     and `cd backend && uv sync` could never have found its file.

Defect 3 is the one that survives fixing the other two, so it is tested most
closely here: the paths must arrive with their structure intact.
"""

from pathlib import Path

from app.repositories.baseline import missing_tool, run_baseline
from app.sandboxes.environment import (
    ALLOWED_PACKAGES,
    EnvironmentSpec,
    discover_files,
    installs_into_workspace,
    resolve_environment,
)
from app.sandboxes.exec import CommandResult


def _monorepo(root: Path) -> Path:
    """A repo shaped like the one that failed: manifests one level down."""
    (root / "Makefile").write_text("setup:\n\tcd backend && uv sync\n")
    (root / "backend").mkdir()
    (root / "backend" / "pyproject.toml").write_text('[project]\nname = "x"\n')
    (root / "backend" / "uv.lock").write_text("version = 1\n")
    (root / "frontend").mkdir()
    (root / "frontend" / "package.json").write_text('{"name":"x"}')
    return root


def test_nested_manifests_are_found_and_keep_their_paths(tmp_path: Path) -> None:
    found = discover_files(_monorepo(tmp_path))

    assert Path("Makefile") in found
    # The whole point: not "pyproject.toml", which is where flattening left it.
    assert Path("backend/pyproject.toml") in found
    assert Path("frontend/package.json") in found


def test_a_makefile_repo_gets_make(tmp_path: Path) -> None:
    spec = resolve_environment(_monorepo(tmp_path))
    assert "make" in spec.system_packages


def test_install_command_alone_can_imply_the_tool(tmp_path: Path) -> None:
    """A repo whose Makefile sits deeper than we scan still needs make."""
    spec = resolve_environment(tmp_path, install_cmd="make setup")
    assert "make" in spec.system_packages


def test_c_extension_dependency_asks_for_a_compiler(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("lxml==5.1.0\nrequests\n")
    spec = resolve_environment(tmp_path)
    assert "build-essential" in spec.system_packages


def test_pure_python_repo_installs_nothing_extra(tmp_path: Path) -> None:
    """No speculative packages: a plain repo must not drag in a toolchain."""
    (tmp_path / "requirements.txt").write_text("requests\n")
    assert resolve_environment(tmp_path).system_packages == []


def test_dockerfile_hints_are_read_but_filtered(tmp_path: Path) -> None:
    """A repo Dockerfile is evidence, and the allowlist still governs.

    We never build their Dockerfile — the harnesses live in ours — but what it
    installs tells us what its code needs.
    """
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.12\n"
        "RUN apt-get update && apt-get install -y libpq-dev nmap && rm -rf /var/lib/apt/lists/*\n"
    )
    spec = resolve_environment(tmp_path)

    assert "libpq-dev" in spec.system_packages
    # nmap is not on the allowlist, so it is reported rather than installed.
    assert "nmap" not in spec.system_packages
    assert "nmap" in spec.rejected


def test_every_resolved_package_is_on_the_allowlist(tmp_path: Path) -> None:
    """The invariant, stated directly: nothing reaches apt unvetted."""
    (tmp_path / "Dockerfile").write_text(
        "RUN apt-get install -y make curl-dev totally-made-up libssl-dev\n"
    )
    (tmp_path / "Makefile").write_text("all:\n\techo hi\n")
    spec = resolve_environment(tmp_path)
    assert set(spec.system_packages) <= ALLOWED_PACKAGES


def test_identity_changes_with_the_package_set() -> None:
    """Two different environments must not share one cached image."""
    a = EnvironmentSpec(system_packages=["make"], copy_paths=[Path("Makefile")])
    b = EnvironmentSpec(system_packages=["make", "build-essential"], copy_paths=[Path("Makefile")])
    assert a.identity() != b.identity()


def test_identity_is_order_independent() -> None:
    """…but the same environment must not rebuild because a list got reordered."""
    a = EnvironmentSpec(system_packages=["make", "gcc"], copy_paths=[Path("a"), Path("b")])
    b = EnvironmentSpec(system_packages=["gcc", "make"], copy_paths=[Path("b"), Path("a")])
    assert a.identity() == b.identity()


def test_workspace_local_installers_are_not_baked_into_an_image() -> None:
    """Caching only helps when the mount cannot hide the result.

    Containers bind-mount the host workspace over /workspace. `uv sync` writes
    `.venv` and `npm install` writes `node_modules` — both inside the project,
    both invisible the moment that mount lands. Building them costs minutes and
    buys nothing, so the build is skipped and the install runs in-container.
    """
    for cmd in [
        "uv sync",
        "cd backend && uv sync",
        "npm install",
        "npm ci",
        "pnpm install",
        "poetry install",
        "make setup",
    ]:
        assert installs_into_workspace(cmd), cmd


def test_site_packages_installers_are_still_cached() -> None:
    """pip lands outside the mount, which is the case the cache was built for."""
    for cmd in [
        "pip install -r requirements.txt",
        "python -m pip install -r requirements.txt",
        "pip install -e .",
    ]:
        assert not installs_into_workspace(cmd), cmd


def test_no_install_command_is_not_workspace_local() -> None:
    assert installs_into_workspace(None) is False
    assert installs_into_workspace("") is False


def test_missing_tool_is_named_from_the_build_log() -> None:
    for text, expected in [
        ("/bin/sh: 1: make: not found", "make"),
        ("bash: uv: command not found", "uv"),
        ("sh: command not found: poetry", "poetry"),
    ]:
        result = CommandResult(command="x", exit_code=127, stdout=text, stderr="", duration_s=0.1)
        assert missing_tool(result) == expected


def test_a_genuine_failure_is_not_mistaken_for_a_missing_tool() -> None:
    result = CommandResult(
        command="pip install -r requirements.txt",
        exit_code=1,
        stdout="ERROR: Could not find a version that satisfies the requirement foo",
        stderr="",
        duration_s=0.1,
    )
    assert missing_tool(result) is None


def test_failed_install_warns_and_still_runs_the_tests(tmp_path: Path) -> None:
    """A missing tool must not be reported as "this repo cannot be scored".

    Plenty of repos are stdlib-only or vendored and pass their suite with no
    install at all. Halting on the install threw those away.
    """
    install = CommandResult(
        command="make setup",
        exit_code=127,
        stdout="/bin/sh: 1: make: not found",
        stderr="",
        duration_s=0.2,
    )

    def execute(cmd: str, cwd: Path) -> CommandResult:
        return CommandResult(
            command=cmd,
            exit_code=0,
            stdout="test_a PASSED\ntest_b PASSED\n2 passed",
            stderr="",
            duration_s=0.1,
        )

    outcome = run_baseline(
        tmp_path, {"test": "pytest -q"}, "pytest", execute=execute, prebuilt_install=install
    )

    assert outcome.benchmarkable is True
    assert outcome.warn is True
    # And the reason is stated in words the user can act on.
    assert "make" in outcome.steps["install"]["diagnosis"]
    assert "sandbox image" in outcome.steps["install"]["diagnosis"]


def test_failed_install_plus_dead_suite_is_still_no_signal(tmp_path: Path) -> None:
    """Degrading must not become papering over."""
    install = CommandResult(
        command="make setup", exit_code=127, stdout="make: not found", stderr="", duration_s=0.2
    )

    def execute(cmd: str, cwd: Path) -> CommandResult:
        return CommandResult(
            command=cmd,
            exit_code=1,
            stdout="No module named pytest",
            stderr="",
            duration_s=0.1,
        )

    outcome = run_baseline(
        tmp_path, {"test": "pytest -q"}, "pytest", execute=execute, prebuilt_install=install
    )
    assert outcome.benchmarkable is False
