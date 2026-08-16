import json
from pathlib import Path

from app.repositories.detectors import analyze_repository


def make_python_repo(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.12"\n'
        '[tool.ruff]\nline-length = 100\n[tool.mypy]\nstrict = true\n'
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
    )
    (root / "uv.lock").write_text("")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_ok(): pass\n")


def test_python_detection(tmp_path: Path) -> None:
    make_python_repo(tmp_path)
    result = analyze_repository(tmp_path)
    assert "python" in result.languages
    assert result.supported
    assert result.package_managers == ["uv"]
    assert result.commands.install == "uv sync"
    # `python -m pytest`, not bare `pytest`: the module form puts the CURRENT
    # directory on sys.path. Bare pytest puts the first parent without
    # __init__.py there (usually `tests/`), so a src-layout repo with no pytest
    # config cannot import its own package. Do not "simplify" this back.
    assert result.commands.test == "uv run python -m pytest -v"
    assert result.commands.test_framework == "pytest"
    assert result.commands.lint == "uv run ruff check ."
    assert result.commands.typecheck == "uv run mypy ."
    assert result.runtime_versions["python"] == ">=3.12"
    assert "tests" in result.test_locations


def test_requirements_repo_uses_module_forms(tmp_path: Path) -> None:
    """`python -m pip`, not bare `pip`.

    A bare `pip` resolves independently of `python`, so on a machine with more
    than one interpreter it installs somewhere the tests never look — reporting
    success while the tests fail on the dependency it just "installed".
    """
    (tmp_path / "requirements.txt").write_text("pandas==2.3.2\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_ok(): pass\n")

    commands = analyze_repository(tmp_path).commands
    assert commands.install == "python -m pip install -r requirements.txt"
    assert commands.test == "python -m pytest -v"


def test_src_layout_repo_gets_an_importable_test_command(tmp_path: Path) -> None:
    """The Pokemon-Battle-Simulator shape: package `src/` with __init__.py,
    `tests/` without one, and no pytest config anywhere. Bare `pytest` puts
    `tests/` on sys.path and the repo root never gets there, so `import src`
    raises ModuleNotFoundError."""
    (tmp_path / "requirements.txt").write_text("pandas\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "thing.py").write_text("VALUE = 1\n")
    (tmp_path / "tests").mkdir()  # deliberately no __init__.py
    (tmp_path / "tests" / "test_thing.py").write_text(
        "from src.thing import VALUE\n\ndef test_v():\n    assert VALUE == 1\n"
    )

    test_cmd = analyze_repository(tmp_path).commands.test
    assert test_cmd == "python -m pytest -v"
    assert not test_cmd.startswith("pytest"), "bare pytest cannot import src/ here"


def test_node_detection(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {"build": "vite build", "test": "vitest run", "lint": "eslint ."},
                "engines": {"node": ">=20"},
            }
        )
    )
    (tmp_path / "tsconfig.json").write_text("{}")
    result = analyze_repository(tmp_path)
    assert "typescript" in result.languages
    assert result.supported
    assert result.commands.install == "npm install"
    assert result.commands.test == "npm test"
    assert result.commands.test_framework == "vitest"
    assert result.commands.typecheck == "npx tsc --noEmit"
    assert result.runtime_versions["node"] == ">=20"


def test_unsupported_language_reported(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x\n")
    result = analyze_repository(tmp_path)
    assert "go (unsupported)" in result.languages
    assert not result.supported


def test_ci_workflows_detected(tmp_path: Path) -> None:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("name: ci\n")
    result = analyze_repository(tmp_path)
    assert result.ci_workflows == [".github/workflows/ci.yml"]
