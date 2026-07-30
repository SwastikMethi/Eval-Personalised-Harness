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
    assert result.commands.test == "uv run pytest -v"
    assert result.commands.test_framework == "pytest"
    assert result.commands.lint == "uv run ruff check ."
    assert result.commands.typecheck == "uv run mypy ."
    assert result.runtime_versions["python"] == ">=3.12"
    assert "tests" in result.test_locations


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
